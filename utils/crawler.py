import hashlib
import logging
import os

import requests
from langchain_community.document_loaders import BSHTMLLoader
from bs4 import Tag
from langchain_text_splitters import HTMLSemanticPreservingSplitter
from bs4 import BeautifulSoup
from urllib.parse import urljoin

CACHE_DIR = "cache"

logger = logging.getLogger(__name__)

class Crawler:

    def __init__(self, starturl, max_sites=100):
        self.starturl = starturl
        self.visited_urls = []
        self.urls_to_visit = [starturl]
        self.site_docs = {}
        self.max_sites = max_sites
        self.done_sites = 0
        self.request_session = requests.Session()

        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)


    @staticmethod
    def url_to_file_name(url):
        return (CACHE_DIR+"/"+hashlib.md5(url.encode('utf-8')).hexdigest()+
                (url
                .replace('/', '-')
                .replace('?', '_')
                .replace(':', '')
                )+".html")

    def get_and_cache(self, url):

        file_name = Crawler.url_to_file_name(url)
        if os.path.isfile(file_name):
            with open(file_name, "rb") as file:
                url_text = file.read()
        else:
            response = self.request_session.get(url)
            url_text = response.content.decode(response.encoding).encode("utf-8")
            fh = open(file_name, 'wb')
            fh.write(url_text)
            fh.close()

        return {"file_name": file_name, "url_text": url_text}

    def download_url(self, url):
        site_content = self.get_and_cache(url)
        # html_loader = BSHTMLLoader(file_path=site_content['file_name'], open_encoding="utf-8")
        # raw_docs = html_loader.load()
        headers_to_split_on = [
            ("h1", "Header 1"),
            ("h2", "Header 2"),
            ("h3", "Header 3"),
            ("h4", "Header 4"),
        ]

        splitter = HTMLSemanticPreservingSplitter(
            headers_to_split_on=headers_to_split_on,
            separators=["\n\n", "\n", ". ", "! ", "? "],
            max_chunk_size=30000,
            preserve_images=True,
            preserve_videos=True,
            elements_to_preserve=["table", "ul", "ol", "code"],
            denylist_tags=["script", "style", "head"],
        )

        raw_docs = splitter.split_text(site_content['url_text'].decode("utf-8"))
        clean_docs = []
        for raw_doc in raw_docs:
            if len(raw_doc.page_content) > 0:
                if "We have over 624,000 electricity connections" in raw_doc.page_content:
                    logger.info("################ FOUND")
                clean_docs.append(raw_doc)

        self.site_docs[url] = clean_docs
        return site_content['url_text']

    @staticmethod
    def get_linked_urls(url, html):
        soup = BeautifulSoup(html, 'html.parser')
        for link in soup.find_all('a'):
            path = link.get('href')
            if path and path.startswith('/'):
                path = urljoin(url, path)
            yield path

    def add_url_to_visit(self, url):
        if url and url.startswith(self.starturl) and url not in self.visited_urls and url not in self.urls_to_visit:
            self.urls_to_visit.append(url)

    def crawl(self, url):
        html = self.download_url(url)
        for url in Crawler.get_linked_urls(url, html):
            self.add_url_to_visit(url)

    def run(self):
        while self.urls_to_visit and self.done_sites < self.max_sites:
            url = self.urls_to_visit.pop(0)
            logging.info(f'Crawling: {url} visited: {len(self.visited_urls)} todo: {len(self.urls_to_visit)}')
            try:
                self.crawl(url)
            except Exception:
                logging.exception(f'Failed to crawl: {url}')
            finally:
                self.visited_urls.append(url)
            self.done_sites += 1
            no = 1
        for url, docs in self.site_docs.items():
            print(f"{no}========== {url} =========")
            no += 1

            for doc in docs:
                print(f"========== {doc.metadata} size: {len(doc.page_content)} =========")

        print(f"Status visited: {len(self.visited_urls)} todo: {len(self.urls_to_visit)}")

    def get_site_docs(self):
        return self.site_docs
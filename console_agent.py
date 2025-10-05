import os

import boto3
import json

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from requests_aws4auth import AWS4Auth
from opensearchpy import RequestsHttpConnection, OpenSearch


def invoke_model(prompt):

    model_id = "amazon.nova-micro-v1:0"
    native_request = {
        "schemaVersion": "messages-v1",
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 500, "topK": 20, "temperature": 0.7}
    }
    # Convert the native request to JSON.
    request = json.dumps(native_request)
    try:
        # Invoke the model with the request.
        response = bedrock.invoke_model(modelId=model_id, body=request)

    except (ClientError, Exception) as e:
        print(f"ERROR: Can't invoke '{model_id}'. Reason: {e}")
        exit(1)
    # Decode the response body.
    model_response = json.loads(response["body"].read())
    # Extract and print the response text.
    response_text = model_response['output']['message']['content'][0]['text'].replace('\\n', '\n')
    return response_text


if __name__ == '__main__':
    load_dotenv()

    region = os.getenv("AWS_REGION")
    service = "aoss"
    aoss_host = os.getenv("AOSS_HOST")

    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, service, session_token=credentials.token)

    input_text = os.getenv('TEST_QUESTION')

    bedrock = boto3.client("bedrock-runtime", region_name=region)
    response = bedrock.invoke_model(
        modelId=os.getenv('TEXT_EMBEDDING_MODEL'),
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": input_text})
    )
    query_vector = json.loads(response['body'].read())['embedding']

    opensearch_client = OpenSearch(
        hosts=[{'host': aoss_host, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=20,
    )

    response = opensearch_client.search(
        index=os.getenv("OPENSEARCH_INDEX"),
        body={
            "size": 5,
            "query": {
                "knn": {
                    "vector_field": {
                        "vector": query_vector,
                        "k": 5
                    }
                }
            }
        }
    )

    context = "\n".join([doc['_source']["text"] for doc in response['hits']['hits']])
    prompt_without_context = f"Question: {input_text}"
    prompt = f"Answer based on context:\n{context}\n\nQuestion: {input_text}"

    print('#' * 8 + " Result without RAG " + '#' * 8)
    print(invoke_model(prompt_without_context))
    print('#' * 8 + " Result with RAG " + '#' * 8)
    print(invoke_model(prompt))

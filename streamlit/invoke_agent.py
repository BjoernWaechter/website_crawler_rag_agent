import os
import json
import base64
import io
import sys
import boto3

from boto3.session import Session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from requests import request
from dotenv import load_dotenv
from requests_aws4auth import AWS4Auth
from opensearchpy import RequestsHttpConnection, OpenSearch

load_dotenv()

region = os.getenv("AWS_REGION")
# ---------------------------------------------------------------------
# Replace with your actual Agent ID and Alias ID below:
# ---------------------------------------------------------------------



# ---------------------------------------------------------------------
# REGION CONFIGURATION:
# ---------------------------------------------------------------------
os.environ["AWS_REGION"] = region
aoss_host = os.getenv("OPENSEARCH_HOST")

service = "aoss"
bedrock = boto3.client("bedrock-runtime", region_name=region)


# ---------------------------------------------------------------------
# HELPER FUNCTION TO GET AWS CREDENTIALS SAFELY
# ---------------------------------------------------------------------
def get_frozen_credentials():
    """
    Safely obtain frozen AWS credentials from the current Boto3 Session.
    Raise an error if credentials are not found to clarify what's missing.
    """
    session = Session()
    creds = session.get_credentials()
    if not creds:
        raise EnvironmentError(
            "No valid AWS credentials found. Ensure you've configured AWS credentials "
            "correctly (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, etc.) or set up an "
            "AWS profile that Boto3 can discover."
        )
    return creds.get_frozen_credentials()


# ---------------------------------------------------------------------
# SIGNED REQUEST FUNCTION
# ---------------------------------------------------------------------
def sigv4_request(
        url,
        method='GET',
        body=None,
        params=None,
        headers=None,
        service='execute-api',
        region=None,
        credentials=None
):
    """
    Sends an HTTP request signed with SigV4.

    Args:
        url: The request URL (e.g. 'https://www.example.com').
        method: The request method ('GET', 'POST', 'PUT', 'DELETE'). Defaults to 'GET'.
        body: The request body (e.g. json.dumps({ 'foo': 'bar' })). Defaults to None.
        params: The request query params (e.g. { 'foo': 'bar' }). Defaults to None.
        headers: The request headers (e.g. { 'content-type': 'application/json' }).
        service: The AWS service name. Defaults to 'execute-api'.
        region: The AWS region. Defaults to whatever is set by the environment variable "AWS_REGION".
        credentials: The AWS credentials to use. Defaults to get_frozen_credentials().
    Returns:
        The HTTP response (requests.Response object).
    """
    if region is None:
        region = os.environ.get("AWS_REGION", "us-west-2")
    if credentials is None:
        credentials = get_frozen_credentials()

    # sign request
    req = AWSRequest(
        method=method,
        url=url,
        data=body,
        params=params,
        headers=headers
    )
    SigV4Auth(credentials, service, region).add_auth(req)
    prepared_req = req.prepare()

    # send request
    return request(
        method=prepared_req.method,
        url=prepared_req.url,
        headers=prepared_req.headers,
        data=prepared_req.body
    )

def invoke_model(prompt):

    model_id = "amazon.nova-micro-v1:0"
    native_request = {
        "schemaVersion": "messages-v1",
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 200, "topK": 20, "temperature": 0.7}
    }
    # Convert the native request to JSON.
    request = json.dumps(native_request)
    response = bedrock.invoke_model(modelId=model_id, body=request)
    # Decode the response body.
    model_response = json.loads(response["body"].read())
    # Extract and print the response text.
    response_text = model_response['output']['message']['content'][0]['text'].replace('\\n', '\n')
    return response_text


# ---------------------------------------------------------------------
# ASK QUESTION / INVOKE AGENT
# ---------------------------------------------------------------------
def askQuestion(question):
    """
    Sends a JSON POST request to the Bedrock Agent endpoint and returns the
    captured output (for debugging) and the final LLM response text.
    """
    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, service, session_token=credentials.token)

    response = bedrock.invoke_model(
        modelId=os.getenv('TEXT_EMBEDDING_MODEL'),
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": question})
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
            "size": int(os.getenv("OPENSEARCH_MAX_RESULT")),
            "query": {
                "knn": {
                    "vector_field": {
                        "vector": query_vector,
                        "k": int(os.getenv("OPENSEARCH_MAX_RESULT"))
                    }
                }
            }
        }
    )

    context = "\n".join([doc['_source']["text"] for doc in response['hits']['hits']])
    prompt = f"Answer based on context:\n{context}\n\nQuestion: {question}"
    prompt_without_context = f"Question: {question}"

    return invoke_model(prompt) + "\n========== Without RAG context ==============\n" + invoke_model(prompt_without_context)


# ---------------------------------------------------------------------
# DECODE RESPONSE
# ---------------------------------------------------------------------
def decode_response(response):
    """
    Decodes the chunked/streamed response, looking for base64-encoded
    segments. Returns a tuple of (debug_string, final_response).
    """
    captured_output = io.StringIO()
    sys.stdout = captured_output

    string = ""
    for line in response.iter_content():
        try:
            string += line.decode(encoding='utf-8')
        except:
            # If a particular chunk can't be decoded as UTF-8, just skip it
            continue

    # print("Decoded response:", string)
    split_response = string.split(":message-type")
    # print(f"Split Response: {split_response}")
    # print(f"Length of split: {len(split_response)}")

    final_response = ""
    for idx in range(len(split_response)):
        if "bytes" in split_response[idx]:
            encoded_last_response = split_response[idx].split("\"")[3]
            decoded = base64.b64decode(encoded_last_response)
            final_response_chunk = decoded.decode('utf-8')
            print(final_response_chunk)
        else:
            print(f"No bytes at index {idx}")
            print(split_response[idx])

    # Attempt to parse the last part for finalResponse
    last_response = split_response[-1]
    # print(f"Last Response: {last_response}")
    if "bytes" in last_response:
        # print("Bytes in last response")
        encoded_last_response = last_response.split("\"")[3]
        decoded = base64.b64decode(encoded_last_response)
        final_response = decoded.decode('utf-8')
    else:
        # print("No bytes in last response")
        part1 = string[string.find('finalResponse') + len('finalResponse":'):]
        part2 = part1[:part1.find('"}') + 2]
        final_response = json.loads(part2)['text']

    # Cleanup the final response
    final_response = final_response.replace("\"", "")
    final_response = final_response.replace("{input:{value:", "")
    final_response = final_response.replace(",source:null}}", "")

    # Restore original stdout
    sys.stdout = sys.__stdout__

    # Get debug string
    captured_string = captured_output.getvalue()

    return captured_string, final_response


# ---------------------------------------------------------------------
# LAMBDA HANDLER (if used in AWS Lambda)
# ---------------------------------------------------------------------
def lambda_handler(event, context):
    """
    AWS Lambda entry point that handles incoming events, obtains a response from
    askQuestion, and returns structured JSON data.
    """
    sessionId = event["sessionId"]
    question = event["question"]
    endSession = False

    print(f"Session: {sessionId} asked question: {question}")

    try:
        if event.get("endSession") == "true":
            endSession = True
    except:
        endSession = False


    try:
        response = askQuestion(question)
        return {
            "status_code": 200,
            "body": json.dumps({"response": response})
        }
    except Exception as e:
        return {
            "status_code": 500,
            "body": json.dumps({"error": str(e)})
        }

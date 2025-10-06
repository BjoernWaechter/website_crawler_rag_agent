import logging
import os
import uuid

import invoke_agent as agenthelper
import streamlit as st
import json
import pandas as pd
from PIL import Image, ImageOps, ImageDraw
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

logger = logging.getLogger(__name__)

# Streamlit page configuration
st.set_page_config(page_title=f"Get info about the {os.getenv('NAME_OF_WEBSITE')} website", page_icon=":robot_face:", layout="wide")


# Function to crop image into a circle
def crop_to_circle(image):
    mask = Image.new('L', image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0) + image.size, fill=255)
    result = ImageOps.fit(image, mask.size, centering=(0.5, 0.5))
    result.putalpha(mask)
    return result


# Title
st.title(f"Get info about the {os.getenv('NAME_OF_WEBSITE')} website")

# Display a text box for input
prompt = st.text_input("Please enter your query?", max_chars=2000)
prompt = prompt.strip()

# Display a primary button for submission
submit_button = st.button("Submit", type="primary")


# Session State Management
if 'history' not in st.session_state:
    st.session_state['history'] = []


# Function to parse and format response
def format_response(response_body):
    try:
        # Try to load the response as JSON
        data = json.loads(response_body)
        # If it's a list, convert it to a DataFrame for better visualization
        if isinstance(data, list):
            return pd.DataFrame(data)
        else:
            return response_body
    except json.JSONDecodeError:
        # If response is not JSON, return as is
        return response_body


# Handling user input and responses
if submit_button and prompt:

    logger.info(f"Prompt: {prompt}")
    event = {
        "sessionId": "MYSESSION",
        "question": prompt
    }
    response = agenthelper.lambda_handler(event, None)

    try:
        # Parse the JSON string
        if response and 'body' in response and response['body']:
            response_data = json.loads(response['body'])
            # print("RESPONSE DATA ->  ", response_data)
        else:
            logger.error("Invalid or empty response received")
    except json.JSONDecodeError as e:
        logger.error("JSON decoding error:", e)
        response_data = None

    try:
        # Extract the response and trace data
        all_data = format_response(response_data['response'])
    except:
        all_data = "..."

    st.session_state['history'].append({"question": prompt, "answer": all_data})


# Display conversation history
st.write("## Conversation History")

# Load images outside the loop to optimize performance
human_image = Image.open('images/human_face.png')
robot_image = Image.open('images/robot_face.jpg')
circular_human_image = crop_to_circle(human_image)
circular_robot_image = crop_to_circle(robot_image)

# logger.info(st.session_state['history'])

for index, chat in enumerate(reversed(st.session_state['history'])):
    with st.container(key=uuid.uuid4()):
        logger.info(f'{index}: {chat["question"]}')
        # Creating columns for Question
        col1_q, col2_q = st.columns([2, 10])
        with col1_q:
            st.image(circular_human_image, width=125)
        with col2_q:
            # Generate a unique key for each question text area
            st.text_area("Q:", value=chat["question"], height=68, key=uuid.uuid4(), disabled=True)

        # Creating columns for Answer
        col1_a, col2_a = st.columns([2, 10])
        if isinstance(chat["answer"], pd.DataFrame):
            with col1_a:
                st.image(circular_robot_image, width=100)
            with col2_a:
                # Generate a unique key for each answer dataframe
                st.dataframe(chat["answer"], key=f"answer_df_{index}")
        else:
            with col1_a:
                st.image(circular_robot_image, width=150)
            with col2_a:
                # Generate a unique key for each answer text area
                st.text_area("A:", value=chat["answer"], height=400, key=uuid.uuid4())

# Example Prompts Section
st.write("## Test Prompts")

test_prompts = eval(os.getenv("TEST_QUESTIONS"))

# Creating a list of prompts for the Knowledge Base section
knowledge_base_prompts = [{"Prompt": q} for q in test_prompts]

# Displaying the Knowledge Base prompts as a table
st.table(knowledge_base_prompts)

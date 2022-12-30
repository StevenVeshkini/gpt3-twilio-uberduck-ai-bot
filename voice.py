"""
Instructions: 
1) Setup ngrok and run `ngrok http 3000`.
2) Follow the setup instructions here to link your Twilio phone number to this script via webhook
https://www.twilio.com/docs/voice/tutorials/how-to-respond-to-incoming-phone-calls/python

"""

from dotenv import load_dotenv
from flask import Flask, session, request
import os
import redis
from twilio.twiml.voice_response import VoiceResponse, Gather
import openai
import requests
import time
import uuid

load_dotenv()

UBERDUCK_PUBLIC_KEY = os.getenv("UBERDUCK_PUBLIC_KEY")
UBERDUCK_SECRET_KEY = os.getenv("UBERDUCK_SECRET_KEY")
UBERDUCK_ID = os.getenv("UBERDUCK_ID")

openai.api_key = os.getenv("OPENAI_API_KEY")
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
red = redis.Redis('localhost')

BASE_PROMPT = f"""
Pretend to be a friend. Continue the conversation in a colloquial manner, using simple everyday vocabulary.

You: Hey, who is this~?
"""

@app.route('/voice', methods=['GET', 'POST'])
def welcome():
    response = VoiceResponse()
    print(str(session.items()))
    if session.get('welcome') is None:
        # Set Session Variables
        caller = request.form.get('Caller')
        call_sid = request.form.get('CallSid')
        session['caller'] = caller
        session['call_sid'] = call_sid
        session['welcome'] = False
        session['loops'] = 0

        path = None
        while not path:
            path = text_to_speech("Hey, who is this~?")
        # Greet Caller
        gather = Gather(input="speech", enhanced=True, speech_timeout=2)
        gather.play(path)
        response.append(gather)
        session['welcome'] = True
        print(f"AI: Hey, who is this~?")
        red.set(call_sid, BASE_PROMPT)
    else:
        call_sid = request.form.get('CallSid')
        speech_result = request.form.get('SpeechResult')
        print(f"SPEAKER: {speech_result}")
        prev_prompt = red.get(session['call_sid']).decode("utf-8")
        curr_prompt = f"""
        {prev_prompt}
        Them:
        {speech_result}
        You:"""
        ai_response = get_gpt3_response(curr_prompt).strip()
        print(f"AI: {ai_response}")
        new_prompt = f"""
        {curr_prompt}{ai_response}
        """
        path = None
        while not path:
            path = text_to_speech(ai_response)
        red.set(call_sid, new_prompt)
        gather = Gather(input="speech", enhanced=True, speech_timeout=2)
        gather.play(path)
        response.append(gather)

    session['loops'] = session.get('loops') + 1
    print(f"LOOPS: {session['loops']}")
    return str(response)

def get_gpt3_response(prompt):
    completion = openai.Completion.create(model="text-davinci-003", prompt=prompt, max_tokens=256)
    response = completion["choices"][0]["text"]
    return response

def text_to_speech(text: str) -> str:
    """
    This function is a hack to get around Uberduck's S3 bucket not working with Twilio.
    """
    url = "https://api.uberduck.ai/speak-synchronous"
    payload = {
        "voice": "dream-clay",
        "speech": text
    }
    headers = {
        "accept": "application/json",
        "uberduck-id": UBERDUCK_ID,
        "content-type": "application/json"
    }
    response = requests.post(url, json=payload, headers=headers, auth=(UBERDUCK_PUBLIC_KEY, UBERDUCK_SECRET_KEY))
    response = requests.put(f"https://transfer.sh/{str(uuid.uuid4())}.wav", data=response.content)
    url = response.text
    return url

def text_to_speech_uberduck_hosting(text: str) -> str:
    """
    This is the prefered method of getting Uberduck voice files, but their S3 bucket doesn't work with Twilio for some reason.
    """
    url = "https://api.uberduck.ai/speak"
    payload = {
        "voice": "dream-clay",
        "speech": text
    }
    headers = {
        "accept": "application/json",
        "uberduck-id": UBERDUCK_ID,
        "content-type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, auth=(UBERDUCK_PUBLIC_KEY, UBERDUCK_SECRET_KEY))
    uuid = response.json()['uuid']
    url = f"https://api.uberduck.ai/speak-status?uuid={uuid}"
    path = None
    while not path:
        response = requests.get(url, auth=(UBERDUCK_PUBLIC_KEY, UBERDUCK_SECRET_KEY))
        result = response.json()
        failed_at = result["failed_at"]
        path = result["path"]
        if failed_at:
            print('TTS failed.')
            return None
        time.sleep(0.5)
    return path

if __name__ == "__main__":
    app.run(debug=True, port=3000)
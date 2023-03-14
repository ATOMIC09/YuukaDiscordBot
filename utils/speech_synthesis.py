import os
import azure.cognitiveservices.speech as speechsdk
from langdetect import detect

def tts(text, language_voice_code=""):
    # This example requires environment variables named "SPEECH_KEY" and "SPEECH_REGION"
    speech_config = speechsdk.SpeechConfig(subscription=os.environ.get('SPEECH_KEY'), region=os.environ.get('SPEECH_REGION'))
    language = ""

    # Set TTS Language
    if language_voice_code == "": # If language is not specified, detect language
        language = detect(text)     
        print("TTS Detected Language : " + language)

    if language in ['en', 'th', 'ja']: 
        language_code = {'en':'en-US-AnaNeural', 'th':'th-TH-PremwadeeNeural', 'ja':'ja-JP-AoiNeural'}
        speech_config.speech_synthesis_voice_name=language_code[language]
    else:
        speech_config.speech_synthesis_voice_name=language_voice_code


    # Set output file name
    output_file = "temp/output.wav"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_file)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    speech_synthesis_result = speech_synthesizer.speak_text_async(text).get()

    if speech_synthesis_result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized for text [{}]".format(text))
    elif speech_synthesis_result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = speech_synthesis_result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))

        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            if cancellation_details.error_details:
                print("Error details: {}".format(cancellation_details.error_details))
                print("Did you set the speech resource key and region values?")

if __name__ == "__main__":
    tts("こんにちは",language_voice_code="") # Hello
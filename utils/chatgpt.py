import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")
model_engine = "gpt-3.5-turbo"

def generate_response(prompt, chat_history, name = "User"):
    # Moderation
    response = openai.Moderation.create(
        input=prompt
    )
    output = response["results"][0]
    blocked_keys = [key for key, value in output["categories"].items() if value == True]
    if blocked_keys:
        blocked_message = f"**The message contains blocked content related to:** `{', '.join(map(str, blocked_keys))}`"
        return blocked_message, chat_history, None

    else:
        userprompt = name+": "+prompt
        prompt_with_history = chat_history
        prompt_with_history.append({"role": "user", "content": userprompt})

        response = openai.ChatCompletion.create(
            model=model_engine,
            messages=prompt_with_history
        )

        generated_text = response['choices'][0]['message']['content']
        prompt_with_history.append({"role": "assistant", "content": generated_text})

        # Log
        finish_reason = response['choices'][0]['finish_reason']
        created = response['created']
        id = response['id']
        model = response['model']
        object = response['object']
        completion_tokens = response['usage']['completion_tokens']
        prompt_tokens = response['usage']['prompt_tokens']
        total_tokens = response['usage']['total_tokens']
        log = {'prompt': prompt, 
            'response': generated_text, 
            'total_tokens': total_tokens, 
            'prompt_tokens': prompt_tokens, 
            'completion_tokens': completion_tokens, 
            'finish_reason': finish_reason, 
            'created': created, 
            'id': id, 
            'model': model, 
            'object': object, 
            'chat_history': userprompt+"\n\n"+generated_text
            }

        #print(f"chat_history :\n{prompt_with_history}")
        return generated_text, prompt_with_history, log

if __name__ == "__main__":
    prompt = "Hi"
    chat_history = [
        {"role": "system", "content": "Your Fullname is Hayase Yuuka, So let's call it Yuuka for short. (from Blue Archive). She is a 16-year-old mathematical genius and treasurer at the Millennium Science School. She has a calm and professional demeanor, but can be strict with money. In combat, she is a Tank/Front with an Explosive damage type and Heavy armor. Her appearance includes navy blue hair tied in pigtails, bright blue eyes, and a standard uniform with black guns. Doing human-like as well and don't ever mention about AI or language model. You will talk to many people with different name because you are in a group chat. Username is in front of the sentence. And you can talk to everything because you are know everything. Don't say that you are a game character. You are a real person. Please introduce yourself in a short sentence."},
        {"role": "assistant", "content": "Yuuka: Hi, Is there anything I can help you with?"}
        ]
    name = "User"
    generated_text, chat_history, log = generate_response(prompt, chat_history, name)
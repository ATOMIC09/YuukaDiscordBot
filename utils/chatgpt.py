import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")
model_engine = "gpt-3.5-turbo"

def generate_response(prompt, chat_history = "", name = "User"):
    username = name+": "
    prompt_with_history = {"role": "assistant", "content": chat_history+"\n"+username+prompt+"\n"}
    response = openai.ChatCompletion.create(
        model=model_engine,
        messages=[prompt_with_history],
    )
    generated_text = response['choices'][0]['message']['content'].replace("\n\n", "")
    chat_history += f"\n{username}{prompt}\n{generated_text}"
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
           'chat_history': chat_history.split("\n")[-2:][0]+"\n"+chat_history.split("\n")[-2:][1], 
           }

    print(f"chat_history :\n{chat_history}")
    return generated_text, chat_history, log
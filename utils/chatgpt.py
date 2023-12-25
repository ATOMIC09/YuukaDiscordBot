from openai import OpenAI
import os

client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)
model_engine = "gpt-3.5-turbo-1106"

def generate_response(prompt, chat_history, name = "User"):
    # Moderation
    response = client.moderations.create(
        input=prompt
    )
    output = response.results
    blocked_keys = [key for key, value in output[0].categories if value == True]
 
    if blocked_keys:
        blocked_message = f"**The message contains blocked content related to:** `{', '.join(map(str, blocked_keys))}`"
        return blocked_message, chat_history, None

    else:
        userprompt = name+": "+prompt
        prompt_with_history = chat_history
        prompt_with_history.append({"role": "user", "content": userprompt})

        response = client.chat.completions.create(
            model=model_engine,
            messages=prompt_with_history
        )

        print('response:', response)
        generated_text = response.choices[0].message.content
        prompt_with_history.append({"role": "assistant", "content": generated_text})

        # Log
        finish_reason = response.choices[0].finish_reason
        created = response.created
        id = response.id
        model = response.model
        object = response.object
        completion_tokens = response.usage.completion_tokens
        prompt_tokens = response.usage.prompt_tokens
        total_tokens = response.usage.total_tokens
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

        return generated_text, prompt_with_history, log
    

if __name__ == '__main__':
    print(generate_response('hi', [
        {"role": "system", "content": "You are a girl. Your full name is Hayase Yuuka."},
        {"role": "assistant", "content": "Yuuka: Hello, is there anything I can help you with?"}
        ]))
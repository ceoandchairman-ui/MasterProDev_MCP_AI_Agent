import os
from huggingface_hub import InferenceClient

def test_llm(prompt, model=None, api_key=None, max_tokens=100):
    api_key = api_key or os.getenv("HUGGINGFACE_API_KEY")
    model = model or os.getenv("HUGGINGFACE_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
    if not api_key:
        raise ValueError("HUGGINGFACE_API_KEY not set")
    client = InferenceClient(token=api_key)
    messages = [{"role": "user", "content": prompt}]
    response = client.chat_completion(messages, model=model, max_tokens=max_tokens)
    return response.choices[0].message.content

if __name__ == "__main__":
    print(test_llm("What is your name?"))

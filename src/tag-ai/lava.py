import requests
import base64
import sys
from PIL import Image, ImageOps
from io import BytesIO

# Local Ollama server details
OLLAMA_SERVER = "http://localhost:11434"
MODEL_NAME = "llava"

def preprocess_image(image_path, target_size=(672, 672)):
    """
    Opens an image, converts it to RGB, and resizes it to the target size.
    Uses ImageOps.fit to crop or pad as needed to maintain the aspect ratio.
    """
    img = Image.open(image_path).convert("RGB")
    img = ImageOps.fit(img, target_size, Image.Resampling.LANCZOS)  # Updated line
    return img

def query_llava(prompt, image_path=None):
    """
    Queries a locally running Ollama LLaVA instance via HTTP API with a given prompt.
    If image_path is provided, the image is preprocessed and sent as a Base64-encoded string.
    """
    url = f"{OLLAMA_SERVER}/api/generate"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }
    
    if image_path:
        try:
            # Preprocess the image to the optimal size for LLaVA 1.6 (e.g., 672x672)
            img = preprocess_image(image_path, target_size=(672, 672))
            
            # Save the image to a BytesIO buffer in JPEG format and encode to Base64
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            payload["images"] = [image_base64]
        except FileNotFoundError:
            print(f"Error: File '{image_path}' not found.")
            return

    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        print("\nLLaVA Response:\n", response.json().get("response", "No response received."))
    else:
        print(f"Error: {response.status_code}, {response.text}")

if __name__ == "__main__":
    # Improved prompt instructions:
    improved_prompt = """
Please analyze the provided image and follow these steps:
1. look at image.  
2. Then, list of a mininimum of 15 distinct, tags that capture specific attributes of the image.
3. return the tags in a single line separated by a comma then a space.




"""

    # Get the image file path from the command-line arguments if provided
    image_file = sys.argv[1] if len(sys.argv) > 1 else None

    query_llava(improved_prompt, image_file)

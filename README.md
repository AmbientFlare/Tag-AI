# Tag-AI

Tag-AI is a Python desktop app for tagging and searching photos. Scan folders, generate tags with Ollama or Gemini, and browse and edit the results in a local SQLite catalog. Tag-AI can also write tags to image metadata through ExifTool.

## Run from source

Use Python 3.12 and install the dependencies in a virtual environment:

```sh
git clone https://github.com/AmbientFlare/Tag-AI.git
cd Tag-AI
python -m venv .venv
. .venv/bin/activate
python -m pip install -r src/tag-ai/requirements.txt
python src/tag-ai/main.py
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell. Use the setup wizard to choose a tagging backend and create the catalog. For local tagging, install Ollama and pull a supported vision model. For Gemini, enter your own API key in the app. Gemini tagging sends images to Google. Install ExifTool and make it available on your `PATH` to write tags back to photos.

Try a small folder first. Back up your catalog and original images before writing metadata in bulk.

## Tests

Install pytest in the same environment and run `python -m pytest`. On Linux without a display, set `QT_QPA_PLATFORM=offscreen`.

## License

Tag-AI is released under the [Unlicense](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for the original source citations.

from faster_whisper import WhisperModel
import os

# Ek baar load karo — pehli baar ~810MB download
model = WhisperModel(
    "large-v3-turbo",
    device="cpu",
    compute_type="int8"   # CPU ke liye INT8 — fastest + lowest RAM
)

def transcribe(audio_path: str, lang="hi") -> str:
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=lang,        # "hi" for Hindi, None for auto-detect
        vad_filter=True       # silence skip karo — faster ho jaata hai
    )
    return " ".join([s.text for s in segments])

if __name__ == "__main__":
    audio_file = "P:/Project/ARISE/audia.ogg"
    if os.path.exists(audio_file):
        text = transcribe(audio_file)
        print(text)
        
        # Testing auto-detect
        print("/n--- Testing Auto-Detect ---")
        segments, info = model.transcribe(audio_file, language=None)
        print(f"Detected: {info.language}")
    else:
        print(f"Please provide '{audio_file}' to test.")

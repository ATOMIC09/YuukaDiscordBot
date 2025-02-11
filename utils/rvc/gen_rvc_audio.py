from rvc_python.infer import RVCInference

def gen_audio(input_name: str):
    input_path = f"temp/ai/{input_name}_output.wav"
    rvc = RVCInference(device="cpu") # (I don't have GPU)
    rvc.load_model("utils/rvc/Hayase-Yuuka.pth") # RVC Model from https://huggingface.co/Timur04129/Hayase-Yuuka/resolve/main/Hayase-Yuuka.zip?download=true
    rvc.set_params(f0method="pm", index_rate=0.3, f0up_key=6, protect=0.3)
    rvc.infer_file(input_path, f"temp/ai/{input_name}_outputrvc.wav")
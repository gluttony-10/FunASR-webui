# coding=utf-8

import os
import gradio as gr
import torch
from funasr import AutoModel
import gc
import whisper
import subprocess
import re

os.environ["MODELSCOPE_CACHE"] = "./"

class FunASRApp:
    def __init__(self):
        self.model = None
        self.hotwords = self._load_hotwords()


    def _load_hotwords(self):
        try:
            with open("hotwords.txt", "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "热词 用空格 隔开 十字鱼"


    def load_model(
            self, 
            model, 
            vad_model="fsmn-vad", 
            vad_kwargs={"max_single_segment_time": 30000}, 
            punc_model="ct-punc",  
            spk_model="cam++",
            disable_update=True,
    ):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        if "选择" in model:
            self.model = None
            print(f'\033[31m请先选择加载模型\033[0m')
            return "请先选择加载模型", gr.update(interactive=True)
        elif model == "情感模型":
            punc_model = None
            spk_model = None
            model_name = "iic/SenseVoiceSmall"
        elif model == "热词模型":
            model_name = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        elif model == "情感模型（带时间戳）":
            self.model = AutoModel(
                model= "iic/SenseVoiceSmall", 
                vad_model=vad_model, 
                vad_kwargs=vad_kwargs,
                disable_update=disable_update,
                device="cuda" if torch.cuda.is_available() else "cpu",
            )
            self.model2 = AutoModel(
                model="fsmn-vad", 
                max_end_silence_time=200, 
                disable_update=True, 
                device="cuda" if torch.cuda.is_available() else "cpu"
            )
            print(f'\033[32m{model}加载成功\033[0m')
            return f"{model}加载完成", gr.update(interactive=True)
        elif model == "whisper-large-v3-turbo":
            self.model = whisper.load_model("turbo", download_root="models", device="cuda" if torch.cuda.is_available() else "cpu")
            print(f'\033[32m{model}加载成功\033[0m')
            return f"{model}加载完成", gr.update(interactive=True)
        elif model == "whisper-large-v3":
            self.model = whisper.load_model("large", download_root="models", device="cuda" if torch.cuda.is_available() else "cpu")
            print(f'\033[32m{model}加载成功\033[0m')
            return f"{model}加载完成", gr.update(interactive=True)
        
        print(f'\033[32m开始加载{model}\033[0m')
        self.model = AutoModel(
            model=model_name,  
            vad_model=vad_model, 
            vad_kwargs=vad_kwargs,
            punc_model=punc_model, 
            spk_model=spk_model,
            disable_update=disable_update,
            device="cuda" if torch.cuda.is_available() else "cpu",
        )
        print(f'\033[32m{model}加载成功\033[0m')
        return f"{model}加载完成", gr.update(interactive=True)
    

    def model_inference(
            self,
            model,
            video_input,
            language,
            hotwords,
            format_selector,
            speaker,
            use_itn=True,
            batch_size_s=60, 
            merge_vad=True,
            merge_length_s=15,
            sentence_timestamp=True,
    ):        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        output_path=[]

        with open("hotwords.txt", "w", encoding="utf-8") as f:
            f.write(hotwords)

        if "选择" in model:
            print(f'\033[31m请先选择加载模型\033[0m')
            return "请先选择加载模型", "请先选择加载模型"
        elif model == "情感模型":
            speaker = False
            if format_selector in ["LRC", "SRT"]:
                print(f'\033[31m情感模型仅支持TXT格式\033[0m')
                return "情感模型仅支持TXT格式", "情感模型仅支持TXT格式"
            sentence_timestamp = False
        elif model == "热词模型":
            model = "热词模型"
        elif model == "情感模型（带时间戳）":
            speaker = False
            for input in video_input:
                res = self.model2.generate(input)
                full_text = ""
                sentence_info = []
                for i, value in enumerate(res[0]['value']):
                    start = value[0]/1000
                    end = value[1]/1000
                    filename = os.path.basename(input)
                    filename_without_extension, extension = os.path.splitext(filename)
                    # FFmpeg命令参数
                    os.makedirs("temp", exist_ok=True)
                    temp_path = os.path.join("temp", f"{filename_without_extension}_{i:04d}_{start:.2f}-{end:.2f}{extension}")
                    cmd = [
                        'ffmpeg',
                        '-y',  # 覆盖已存在文件
                        '-ss', str(start),   # 开始时间
                        '-to', str(end),     # 结束时间
                        '-i', input,    # 输入文件
                        '-c', 'copy',        # 流复制（无损快速）
                        temp_path
                    ]
                    # 执行命令
                    try:
                        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        asr_result = self.model.generate(input=temp_path)
                        cleaned_text = re.sub(r'<[^>]+>', '', asr_result[0]["text"])
                        full_text += " " + cleaned_text
                        sentence_info.append({
                            "text": cleaned_text,
                            "start": start * 1000,
                            "end": end * 1000
                        })
                    except subprocess.CalledProcessError as e:
                        print(f"分割失败：{e.stderr.decode()}")
                    finally:
                        # 新增清理代码
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except Exception as e:
                                print(f"清理临时文件失败: {str(e)}")
                res[0].update({
                    "text": full_text.strip(),
                    "sentence_info": sentence_info
                })
                #print(res) # 原始输出
                status_text, content, output_file = self.process_result(res, model, input, format_selector, speaker)
                output_path.append(output_file)
            return status_text, content, gr.update(value=output_path, visible=True)
        elif "whisper" in model:
            speaker = False
            language_abbr = {"自动": None, "中文": "zh", "英文": "en", "粤语": "yue", "日文": "ja", "韩文": "ko", "无语言": "nospeech"}
            language = "自动" if len(language) < 1 else language
            language = language_abbr[language]
            for input in video_input:
                res = self.model.transcribe(input, no_speech_threshold=0.5, logprob_threshold=None, compression_ratio_threshold=2.2, language=language)
                res["sentence_info"] = res.pop("segments")
                for segment in res["sentence_info"]:
                    segment["start"] *= 1000  # 秒 -> 毫秒
                    segment["end"] *= 1000    # 秒 -> 毫秒
                res = [res]
                #print(res) # 原始输出
                status_text, content, output_file = self.process_result(res, model, input, format_selector, speaker)
                output_path.append(output_file)
            return status_text, content, gr.update(value=output_path, visible=True)

        language_abbr = {"自动": "auto", "中文": "zh", "英文": "en", "粤语": "yue", "日文": "ja", "韩文": "ko", "无语言": "nospeech"}
        language = "自动" if len(language) < 1 else language
        language = language_abbr[language]
        
        for input in video_input:
            res = self.model.generate(
                input=input,
                cache={},
                language=language,
                use_itn=use_itn,
                batch_size_s=batch_size_s, 
                merge_vad=merge_vad,
                merge_length_s=merge_length_s,
                sentence_timestamp=sentence_timestamp,
                hotwords=hotwords,
            )
            status_text, content, output_file = self.process_result(res, model, input, format_selector, speaker)
            output_path.append(output_file)
        print(res) # 原始输出
        return status_text, content, gr.update(value=output_path, visible=True)
    

    def process_result(
        self, 
        res, 
        model, 
        input, 
        format_selector, 
        speaker,
    ):
        output_dir = "outputs"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.basename(input)
        filename_without_extension, extension = os.path.splitext(filename)
        
        # 根据格式生成内容
        base_path = os.path.join(output_dir, filename_without_extension)
        if format_selector == "LRC":
            output_file = f"{base_path}.lrc"
            content = self._generate_lrc(res, speaker)
        elif format_selector == "SRT":
            output_file = f"{base_path}.srt"
            content = self._generate_srt(res, speaker)
        else:
            output_file = f"{base_path}.txt"
            if speaker:
                content = ""
                for i in res[0]["sentence_info"]:
                    content += f"说话人{i['spk']}：{i['text']}\n"
            else:
                content = res[0]["text"]

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        status_text = f"{model}识别成功"
        status_text += f"，{format_selector}文件已保存至{output_dir}"

        return status_text, content, output_file


    def _generate_lrc(self, res, speaker):
        """生成标准LRC歌词格式"""
        lrc_lines = []
        for segment in res[0]["sentence_info"]:
            start = self._format_lrc_time(segment.get("start", 0.0))
            if speaker:
                text = f"说话人{segment['spk']}：{segment['text']}"
            else:
                text = segment.get("text", "")
            # 添加类型转换
            if isinstance(text, list):
                text = "".join(text)
            text = text.strip()
            # 简化为只显示开始时间
            lrc_lines.append(f"[{start}]{text}") 
        return "\n".join(lrc_lines)
    

    def _format_lrc_time(self, seconds):
        """LRC时间格式转换（分:秒.厘秒）"""
        seconds /= 1000
        total_seconds = round(seconds, 2)  # 精确到厘秒
        mins = int(total_seconds // 60)
        secs = total_seconds % 60
        return f"{mins:02d}:{secs:05.2f}"  # 示例：37.28秒 → 00:37.28


    def _generate_srt(self, res, speaker):
        """生成标准SRT字幕格式（带序号和时间范围）"""
        srt_lines = []
        for index, segment in enumerate(res[0]["sentence_info"], 1):
            # 时间格式转换（新增带小时的三段式格式）
            start = self._format_srt_time(segment.get("start", 0.0))
            end = self._format_srt_time(segment.get("end", 0.0))
            if speaker:
                text = f"说话人{segment['spk']}：{segment['text']}"
            else:
                text = segment.get("text", "")
            # 添加类型转换
            if isinstance(text, list):
                text = "".join(text)
            text = text.strip()
            
            # 构建字幕块
            srt_lines.append(f"{index}")
            srt_lines.append(f"{start} --> {end}")
            srt_lines.append(f"{text}\n")
        
        return "\n".join(srt_lines)
    

    def _format_srt_time(self, seconds):
        seconds /= 1000
        """SRT专用时间格式转换（小时:分钟:秒,毫秒）"""
        hours = int(seconds // 3600)
        remainder = seconds % 3600
        mins = int(remainder // 60)
        secs = remainder % 60
        return f"{hours:02d}:{mins:02d}:{secs:06.3f}".replace('.', ',')


    def launch(self):
        with gr.Blocks(theme=gr.themes.Soft(), fill_height=True) as demo:
            gr.HTML(html_content)
            with gr.Row():
                with gr.Column():
                    video_input = gr.File(
                        label="上传音视频文件（可多选）", 
                        file_count="multiple",
                        file_types=["video","audio"],
                        type="filepath"
                    )                           
                    with gr.Accordion(label="配置"):
                        model_inputs = gr.Dropdown(
                            label="模型", 
                            choices=["情感模型", "热词模型", "情感模型（带时间戳）", "whisper-large-v3-turbo", "whisper-large-v3", "请先选择加载模型"], 
                            value="请先选择加载模型"
                        )
                        language_inputs = gr.Dropdown(
                            label="语言", 
                            choices=["自动", "中文", "英文", "粤语", "日文", "韩文", "无语言"], 
                            value="自动"
                        )
                        format_selector = gr.Dropdown(
                            label="格式",
                            choices=["TXT", "LRC", "SRT"],
                            value="TXT"
                        )
                        hotwords_inputs = gr.Textbox(label="热词", value=self.hotwords)
                        speaker = gr.Checkbox(label="识别说话人（仅热词模型支持）", value=False)
                    fn_button = gr.Button("开始", variant="primary")
                with gr.Column():
                    status_text = gr.Textbox(label="状态", value="请先选择加载模型", interactive=False)
                    text_outputs = gr.Textbox(label="输出", show_copy_button=True)
                    download_file = gr.File(label="下载文件", visible=False)  # 文件下载组件

            model_inputs.change(
                self.load_model, 
                inputs=model_inputs, 
                outputs=[status_text, model_inputs]
            )
            fn_button.click(
                self.model_inference, 
                inputs=[
                    model_inputs,
                    video_input,
                    language_inputs, 
                    hotwords_inputs,
                    format_selector,
                    speaker,
                ],
                outputs=[status_text, text_outputs, download_file],
                queue=True,
                show_progress=True
            )
        demo.launch(inbrowser=True, share=False, server_name="127.0.0.1")

html_content = """
<div>
    <h2 style="font-size: 30px;text-align: center;">六耳 Liuer</h2>
</div>
<div style="text-align: center;">
    十字鱼
    <a href="https://space.bilibili.com/893892">🌐bilibili</a> 
    |gluttony-10
    <a href="https://github.com/gluttony-10/Liuer">🌐github</a> 
</div>
"""

if __name__ == "__main__":
    print("开源项目：https://github.com/gluttony-10/FunASR-webui bilibili@十字鱼 https://space.bilibili.com/893892 ")
    print(f'\033[32mCUDA版本：{torch.version.cuda}\033[0m')
    print(f'\033[32mPytorch版本：{torch.__version__}\033[0m')
    if torch.cuda.is_available():
        print(f'\033[32m显卡型号：{torch.cuda.get_device_name()}\033[0m')
        total_vram_in_gb = torch.cuda.get_device_properties(0).total_memory / 1073741824
        print(f'\033[32m显存大小：{total_vram_in_gb:.2f}GB\033[0m')
        if torch.cuda.get_device_capability()[0] >= 8:
            print(f'\033[32m支持BF16\033[0m')
            dtype = torch.bfloat16
        else:
            print(f'\033[32m不支持BF16，使用FP16\033[0m')
            dtype = torch.float16
    else:
        print(f'\033[32mCUDA不可用，启用CPUu模式\033[0m')
    app = FunASRApp()
    app.launch()
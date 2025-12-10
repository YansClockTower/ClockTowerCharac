from datetime import datetime
import io
import json
import os
from PIL import Image
from flask import current_app

from app.models.config import get_config


ICON_PATH = ''
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# 辅助函数：检查文件扩展名
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def icon_init():
    global ICON_PATH  # 声明要修改的是全局变量
    if ICON_PATH == '':
        # 3. Get the database path from the config
        if get_config('development'):
            ICON_PATH = get_config('usericon_path_dev')
            print("USRICON_PATH_DEV: " + ICON_PATH)
        else:
            ICON_PATH = get_config('usericon_path')
            print("USRICON_PATH: " + ICON_PATH)

    if not os.path.exists(ICON_PATH):
        os.makedirs(ICON_PATH)

# --- 新增图片处理辅助函数 ---
# --- 修正后的图片处理辅助函数 ---
def process_image(file_storage):
    """
    处理图片：裁剪为居中正方形，处理透明度（转为白底），压缩，并转换为 JPEG 格式。
    返回处理后的图片数据（BytesIO 对象）。
    """
    
    # 1. 从 FileStorage 对象读取图片到内存
    img_stream = io.BytesIO()
    file_storage.save(img_stream)
    img_stream.seek(0)
    
    # 尝试打开图片
    img = Image.open(img_stream)

    # 2. 处理透明度：将透明背景转换为白色背景 (关键修正点)
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        # 创建一个白色背景层
        white_background = Image.new('RGB', img.size, (255, 255, 255))
        
        # 提取 Alpha 通道（如果存在）
        if img.mode in ('RGBA', 'LA'):
            alpha = img.split()[-1]
            
            # 将原始图像粘贴到白色背景上，使用 alpha 通道作为蒙版
            white_background.paste(img, mask=alpha)
            img = white_background
        else:
            # 对于索引颜色带透明度的 PNG，先转换为 RGBA 再处理
            img = img.convert('RGBA')
            alpha = img.split()[-1]
            white_background.paste(img, mask=alpha)
            img = white_background
    else:
        # 如果不是带透明度的格式，直接转换为 RGB
        img = img.convert("RGB") 


    # 3. 裁剪为尽可能大的居中正方形 (保持原逻辑)
    width, height = img.size
    min_dim = min(width, height)
    left = (width - min_dim) / 2
    top = (height - min_dim) / 2
    right = (width + min_dim) / 2
    bottom = (height + min_dim) / 2
    
    img = img.crop((left, top, right, bottom)) # 执行裁剪
    
    
    # 4. 压缩到 100KB 并转换为 JPEG 格式 (修改为 JPEG 及其压缩逻辑)
    
    # 目标文件大小（字节）和初始设置
    target_size_bytes = 100 * 1024 
    MAX_DIMENSION = 512
    
    # 缩小尺寸以控制大小
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    
    output_stream = io.BytesIO()
    
    # 使用二分法查找最佳 JPEG 质量 (100 -> 1)
    quality = 90
    max_quality = 95
    min_quality = 40 # 质量不低于此，以保证可读性
    
    # 尝试一次初始保存
    img.save(output_stream, format="JPEG", quality=quality)

    # 如果文件大小仍然太大，进行迭代降低质量
    current_size = output_stream.getbuffer().nbytes
    
    while current_size > target_size_bytes and quality > min_quality:
        quality -= 5 # 每次降低 5
        output_stream = io.BytesIO() # 重置流
        img.save(output_stream, format="JPEG", quality=quality, optimize=True)
        current_size = output_stream.getbuffer().nbytes
    
    if current_size > target_size_bytes:
         print(f"警告：图片大小 ({current_size / 1024:.2f}KB) 即使质量降到 {quality} 仍超过目标 100KB。")

    return output_stream

def user_icon_url(id):
    icon_init()
    icon_url = f"{ICON_PATH}/{id}.jpg"
    # 4. 检查文件是否存在
    if not os.path.exists(icon_url):
        return f"{ICON_PATH}/default-icon.jpg"
    else:
        return icon_url

def save_user_icon(id, image):
    icon_init()
        # 3. 校验文件类型和扩展名
    if not allowed_file(image.filename):
        return False, "文件类型不受支持"

    try:
        # 1. 处理图片：裁剪、转PNG、压缩
        processed_img_stream = process_image(image)
        
        # 2. 生成安全的文件名 (固定使用 .png 扩展名)
        unique_filename = f"{id}.jpg"
        save_path = os.path.join(ICON_PATH, unique_filename)

        print(save_path)
        # 3. 保存处理后的文件到服务器
        with open(save_path, 'wb') as f:
            f.write(processed_img_stream.getvalue())
        # 7. 返回成功信息和新的头像 URL
        print("头像上传成功。")
        return True, "上传成功。"

    except Exception as e:
        print(f"Image processing or save error: {e}")
        return False, "服务器处理图片失败"
        
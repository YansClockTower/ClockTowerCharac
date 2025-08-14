import requests
from bs4 import BeautifulSoup
import json

example_url = 'https://clocktower-wiki.gstonegames.com/index.php?title=%E4%BE%8D%E5%A5%B3'

# 模拟你给的 HTMLs
def fetch_bloodstar_almanac(url):
    id_map = {
        "how-to-run": "howToRun",
        "tip": "tips",
        "example": "examples"
    }

    response = requests.get(url)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, "html.parser")

    # 最终的 JSON 数据字典
    json_dict = {}

    for target_div in soup.find_all("div", class_="page-contents"):
        parent_li = target_div.find_parent("li")
        li_id = parent_li.get("id") if parent_li else None

        if not li_id:
            continue  # 没有 id 的跳过

        block_data = {}
        # 针对 synopsis 和 overview 特殊处理
        if li_id in ("synopsis", "overview"):
            block_data = target_div.get_text(separator="\n", strip=True)
        else:
            # 按原来规则解析直接子元素
            for child in target_div.find_all(recursive=False):
                tag_name = child.name

                class_list = child.get("class")
                label = ".".join(class_list) if class_list else tag_name

                label = id_map.get(label, label)

                if tag_name == "img":
                    src = child.get("src", "")
                    block_data[label] = src
                elif tag_name == "hr":
                    continue
                elif tag_name == "h2":
                    text = child.get_text(strip=True)
                    if text:
                        li_id = text
                else:
                    text = child.get_text(strip=True)
                    if text:
                        block_data[label] = text

        # 将 li_id 作为 key 存入字典
        json_dict[li_id] = block_data

    return json_dict


def fetch_official_almanac(url):
    response = requests.get(url)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, "html.parser")

    # 找到 id="content" 的 div
    content_div = soup.find("div", id="content")
    if not content_div:
        print("未找到 id='content' 的 div")
        exit()

    # 读取 class="title"
    title_tag = content_div.find(class_="title")
    title_text = title_tag.get_text(strip=True) if title_tag else ""

    # 遍历 h2 标签
    body_content = content_div.find("div", id="mw-content-text")
    if not body_content:
        print("未找到内容主体")
        exit()

    # 标题映射，tips2 会合并
    title_map = {
        "背景故事": "flavor",
        "角色简介": "overview",
        "范例": "examples",
        "运作方式": "howToRun",
        "提示与技巧": "tips",
        # 伪装成XX 动态处理
    }

    content_json = {"title": title_text}

    tips_content = ""
    tips2_content = ""

    for h2 in body_content.find_all("h2"):
        span = h2.find("span", class_="mw-headline")
        if span and span.get("id"):
            section_title = span.get_text(strip=True)

            paragraphs = []
            for sibling in h2.find_next_siblings():
                if sibling.name == "h2":
                    break
                if sibling.name == "p":
                    text = sibling.get_text(strip=True)
                    if text:
                        paragraphs.append(text)
                elif sibling.name in ["ul", "ol"]:
                    for li in sibling.find_all("li"):
                        li_text = li.get_text(strip=True)
                        if li_text:
                            paragraphs.append(li_text)
                elif sibling.name == "pre":
                    text = sibling.get_text(strip=True)
                    if text:
                        paragraphs.append(text)
                elif sibling.name == "div" and "thumb" in sibling.get("class", []):
                    img = sibling.find("img")
                    if img and img.get("src"):
                        paragraphs.append(f"[img]{img['src']}")

            if not paragraphs:
                continue

            text_content = "\n".join(paragraphs)

            # 处理 tips 和 tips2
            if section_title == "提示与技巧":
                tips_content = text_content
            elif section_title.startswith("伪装成"):
                tips2_content = text_content
            else:
                mapped_title = title_map.get(section_title)
                if mapped_title:
                    content_json[mapped_title] = text_content

    # 合并 tips 和 tips2
    combined_tips = ""
    if tips_content:
        combined_tips += f"如果你是{title_text}：\n{tips_content}"
    if tips2_content:
        if combined_tips:
            combined_tips += "\n\n"
        combined_tips += f"伪装成{title_text}：\n{tips2_content}"

    if combined_tips:
        content_json["tips"] = combined_tips

    # 保存为 JSON 字符串
    json_str = json.dumps(content_json, ensure_ascii=False, indent=2)
    print("JSON 数据：")
    print(json_str)
    return content_json

"""Persona 文件读取服务。"""

from json_storage import load_json
from project_config import PERSONA_DIR


def load_personas(persona_dir=PERSONA_DIR, max_count=None):
    """读取 Persona 目录中的 Agent 文件。"""
    persona_files = sorted(persona_dir.glob("agent_*.json"))
    if max_count is not None:
        persona_files = persona_files[:max_count]

    personas = []
    for file_path in persona_files:
        try:
            personas.append(load_json(file_path))
        except Exception as error:
            print(f"跳过无法读取的 Persona {file_path.name}：{error}")
    return personas


def load_first_persona(persona_dir=PERSONA_DIR):
    """读取 Persona 目录中的第一份 Agent 文件。"""
    personas = load_personas(persona_dir, max_count=1)
    if not personas:
        raise FileNotFoundError(f"没有找到 Persona 文件：{persona_dir}")
    return personas[0]


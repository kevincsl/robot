#!/usr/bin/env python3
"""
三角同步 MCP server 設定：Claude Code ↔ Codex ↔ Gemini CLI
依檔案修改時間決定 source of truth，最新的覆蓋其他兩個。
"""

import json
import os
import sys
import argparse
import tomllib
from pathlib import Path
from datetime import datetime

CLAUDE_PATH = Path.home() / ".claude.json"
CODEX_PATH = Path.home() / ".codex" / "config.toml"
GEMINI_PATH = Path.home() / ".gemini" / "settings.json"

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout.reconfigure(encoding="utf-8")


def get_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def read_claude_mcp() -> dict:
    if not CLAUDE_PATH.exists():
        return {}
    data = json.loads(CLAUDE_PATH.read_text("utf-8"))
    return data.get("mcpServers", {})


def read_gemini_mcp() -> dict:
    if not GEMINI_PATH.exists():
        return {}
    data = json.loads(GEMINI_PATH.read_text("utf-8"))
    return data.get("mcpServers", {})


def read_codex_mcp() -> dict:
    if not CODEX_PATH.exists():
        return {}
    text = CODEX_PATH.read_text("utf-8")
    data = tomllib.loads(text)
    raw = data.get("mcp_servers", {})
    servers = {}
    for name, cfg in raw.items():
        srv = {}
        if "url" in cfg:
            srv["type"] = "http"
            srv["url"] = cfg["url"]
            if "bearer_token_env_var" in cfg:
                srv["_bearer_env"] = cfg["bearer_token_env_var"]
        elif "command" in cfg:
            srv["type"] = "stdio"
            cmd = cfg["command"]
            if isinstance(cmd, list):
                srv["command"] = cmd[0] if cmd else ""
                srv["args"] = list(cmd[1:]) if len(cmd) > 1 else []
            else:
                srv["command"] = cmd
                srv["args"] = list(cfg.get("args", []))
            if "env" in cfg:
                srv["env"] = dict(cfg["env"])
        servers[name] = srv
    return servers


def to_claude_format(servers: dict) -> dict:
    out = {}
    for name, srv in servers.items():
        entry = {}
        if srv.get("type") == "stdio":
            entry["type"] = "stdio"
            entry["command"] = srv.get("command", "")
            entry["args"] = srv.get("args", [])
            entry["env"] = srv.get("env", {})
        elif srv.get("type") == "http":
            entry["type"] = "http"
            entry["url"] = srv["url"]
            if "headers" in srv:
                entry["headers"] = srv["headers"]
            elif "_bearer_env" in srv:
                env_var = srv["_bearer_env"]
                token = os.environ.get(env_var, "")
                if token:
                    entry["headers"] = {"Authorization": f"Bearer {token}"}
        out[name] = entry
    return out


def to_gemini_format(servers: dict) -> dict:
    out = {}
    for name, srv in servers.items():
        entry = {}
        if srv.get("type") == "stdio":
            entry["command"] = srv.get("command", "")
            entry["args"] = srv.get("args", [])
            if srv.get("env"):
                entry["env"] = srv["env"]
        elif srv.get("type") == "http":
            entry["url"] = srv["url"]
            if "headers" in srv:
                entry["headers"] = srv["headers"]
        out[name] = entry
    return out


def to_codex_toml_fragment(servers: dict) -> str:
    lines = []
    for name, srv in servers.items():
        lines.append(f"\n[mcp_servers.{name}]")
        if srv.get("type") == "http":
            lines.append(f'url = "{srv["url"]}"')
            if "headers" in srv:
                auth = srv["headers"].get("Authorization", "")
                if auth.startswith("Bearer "):
                    env_var = f"MCP_{name.upper()}_TOKEN"
                    lines.append(f'bearer_token_env_var = "{env_var}"')
                    print(f"  ⚠ Codex 不支援任意 headers，已設定 bearer_token_env_var={env_var}")
                    print(f"    請手動設定環境變數: {env_var}={auth[7:]}")
            elif "_bearer_env" in srv:
                lines.append(f'bearer_token_env_var = "{srv["_bearer_env"]}"')
        elif srv.get("type") == "stdio":
            lines.append(f'command = "{srv.get("command", "")}"')
            args = srv.get("args", [])
            if args:
                toml_arr = ", ".join(f'"{a}"' for a in args)
                lines.append(f"args = [{toml_arr}]")
            env = srv.get("env", {})
            for k, v in env.items():
                lines.append(f'env.{k} = "{v}"')
    return "\n".join(lines) + "\n"


def write_claude_mcp(servers: dict):
    data = json.loads(CLAUDE_PATH.read_text("utf-8")) if CLAUDE_PATH.exists() else {}
    data["mcpServers"] = to_claude_format(servers)
    CLAUDE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def write_gemini_mcp(servers: dict):
    data = json.loads(GEMINI_PATH.read_text("utf-8")) if GEMINI_PATH.exists() else {}
    data["mcpServers"] = to_gemini_format(servers)
    GEMINI_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEMINI_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def write_codex_mcp(servers: dict):
    if not CODEX_PATH.exists():
        print(f"  跳過 Codex：{CODEX_PATH} 不存在")
        return
    text = CODEX_PATH.read_text("utf-8")
    # Remove existing [mcp_servers.*] sections
    lines = text.split("\n")
    out_lines = []
    skip = False
    for line in lines:
        if line.strip().startswith("[mcp_servers."):
            skip = True
            continue
        if skip and line.strip().startswith("[") and not line.strip().startswith("[mcp_servers."):
            skip = False
        if not skip:
            out_lines.append(line)
    # Remove trailing empty lines
    while out_lines and out_lines[-1].strip() == "":
        out_lines.pop()
    new_text = "\n".join(out_lines)
    new_text += "\n" + to_codex_toml_fragment(servers)
    CODEX_PATH.write_text(new_text, "utf-8")


def normalize_servers(servers: dict) -> dict:
    """統一內部格式"""
    out = {}
    for name, srv in servers.items():
        entry = dict(srv)
        if "type" not in entry:
            if "command" in entry:
                entry["type"] = "stdio"
            elif "url" in entry:
                entry["type"] = "http"
        out[name] = entry
    return out


def print_servers(servers: dict, label: str):
    if not servers:
        print(f"  {label}: (無 MCP servers)")
        return
    print(f"  {label}: {len(servers)} 個 servers")
    for name, srv in servers.items():
        stype = srv.get("type", "?")
        if stype == "stdio":
            cmd = srv.get("command", "")
            print(f"    - {name} [stdio] {cmd}")
        elif stype == "http":
            url = srv.get("url", "")
            print(f"    - {name} [http] {url}")


def main():
    parser = argparse.ArgumentParser(description="三角同步 MCP server 設定")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫入")
    parser.add_argument("--source", choices=["claude", "codex", "gemini"], help="強制指定 source")
    args = parser.parse_args()

    print("=== MCP 三角同步 ===\n")

    sources = {
        "Claude Code": (CLAUDE_PATH, read_claude_mcp),
        "Codex": (CODEX_PATH, read_codex_mcp),
        "Gemini CLI": (GEMINI_PATH, read_gemini_mcp),
    }

    mtimes = {}
    all_servers = {}
    for label, (path, reader) in sources.items():
        mt = get_mtime(path)
        mtimes[label] = mt
        servers = reader()
        all_servers[label] = normalize_servers(servers)
        ts = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S") if mt > 0 else "不存在"
        print(f"  {label}: {path}")
        print(f"    修改時間: {ts}")
        print_servers(all_servers[label], "  MCP")
        print()

    source_map = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI"}
    if args.source:
        winner = source_map[args.source]
        source_servers = all_servers[winner]
        if not source_servers:
            print(f"指定的 {winner} 沒有 MCP servers，中止。")
            return
        print(f"📌 以 {winner} 為 source of truth（手動指定）\n")
    else:
        candidates = {k: v for k, v in mtimes.items() if all_servers[k]}
        if not candidates:
            print("所有設定檔都沒有 MCP servers，無法同步。")
            return
        winner = max(candidates, key=candidates.get)
        source_servers = all_servers[winner]
        print(f"📌 以 {winner} 為 source of truth（有 MCP 且最新修改）\n")
    print_servers(source_servers, "同步內容")
    print()

    writers = {
        "Claude Code": write_claude_mcp,
        "Codex": write_codex_mcp,
        "Gemini CLI": write_gemini_mcp,
    }

    for label, writer in writers.items():
        if label == winner:
            print(f"  {label}: 跳過（source）")
            continue
        if args.dry_run:
            print(f"  {label}: 會寫入（dry-run，跳過）")
            continue
        print(f"  {label}: 寫入中...")
        try:
            writer(source_servers)
            print(f"  {label}: ✓ 完成")
        except Exception as e:
            print(f"  {label}: ✗ 失敗 - {e}")

    print("\n=== 同步完成 ===")


if __name__ == "__main__":
    main()

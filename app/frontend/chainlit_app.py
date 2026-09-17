# app/frontend/chainlit_app.py
import os
import chainlit as cl
import requests

# Backend URL. Port 8000 is contended on this machine (other Docker projects
# publish it via Docker Desktop's proxy, which accepts the TCP connection and
# then drops it -> RemoteDisconnected), so default to 8010. Override with the
# API_URL env var if the backend moves again.
API_URL = os.getenv("API_URL", "http://localhost:8010")
REQUEST_TIMEOUT = 30


@cl.on_chat_start
async def start():
    cl.user_session.set("history", [])
    await cl.Message(
        content="Paste a GitHub repo URL to ingest it, or just ask a question if one's already indexed."
    ).send()


@cl.on_message
async def main(message: cl.Message):
    text = message.content.strip()

    if text.startswith("https://github.com/"):
        async with cl.Step(name="Ingesting repo") as step:
            try:
                resp = requests.post(
                    f"{API_URL}/ingest", json={"repo_url": text}, timeout=REQUEST_TIMEOUT
                )
                if resp.status_code == 200:
                    data = resp.json()
                    step.output = f"Indexed {data['chunks_stored']} chunks from {data['repo_name']}"
                else:
                    step.output = f"Ingestion failed ({resp.status_code}): {resp.text}"
            except requests.RequestException as e:
                step.output = f"Could not reach backend at {API_URL}: {e}"
        return  # step.output already shows the result — no need to also send a Message

    history = cl.user_session.get("history", [])

    try:
        async with cl.Step(name="Routing question") as route_step:
            resp = requests.post(
                f"{API_URL}/chat/debug",
                json={"question": text, "history": history},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                route_step.output = f"Backend error ({resp.status_code})"
                await cl.Message(content=f"Something went wrong: {resp.text}").send()
                return
            data = resp.json()
            route_step.output = f"Routed to: {data['route']}"
    except requests.RequestException as e:
        await cl.Message(content=f"Could not reach backend at {API_URL}: {e}").send()
        return

    if data.get("kb_grade"):
        async with cl.Step(name="Grading KB evidence") as grade_step:
            grade_step.output = f"KB grade: {data['kb_grade']}"

    if data.get("web_grade"):
        async with cl.Step(name="Grading web evidence") as grade_step:
            grade_step.output = f"Web grade: {data['web_grade']}"

    await cl.Message(
        content=data["answer"],
        elements=[cl.Text(name="source", content=data["source"], display="inline")],
    ).send()

    # update history for the next turn
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": data["answer"]})
    cl.user_session.set("history", history[-8:])  # cap to last 4 exchanges, same reasoning as router_node's [-4:]
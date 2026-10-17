# app/frontend/chainlit_app.py
import os
import time
import asyncio
import chainlit as cl
import requests

# Backend URL. Port 8000 is contended on this machine (other Docker projects
# publish it via Docker Desktop's proxy, which accepts the TCP connection and
# then drops it -> RemoteDisconnected), so default to 8010. Override with the
# API_URL env var if the backend moves again.
API_URL = os.getenv("API_URL", "http://localhost:8010")
CHAT_TIMEOUT = 120        # /chat/debug can wait out a 25s LLM rate-limit backoff and retry
CONTROL_TIMEOUT = 30      # ingest accept/status: short control-plane calls
POLL_INTERVAL = 2         # seconds between /ingest/status polls


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
                # Ingest runs for minutes (CPU embedding of every chunk), so the
                # backend takes it as a background job and we poll for the stage.
                # A single long request used to time out while the server was
                # still embedding — the repo got indexed but the UI never knew.
                accepted = requests.post(
                    f"{API_URL}/ingest/async", json={"repo_url": text}, timeout=CONTROL_TIMEOUT
                )
                if accepted.status_code != 202:
                    step.output = f"Ingestion failed ({accepted.status_code}): {accepted.text}"
                else:
                    job = accepted.json()
                    started = time.time()
                    while True:
                        poll = requests.get(
                            f"{API_URL}/ingest/status/{job['job_id']}", timeout=CONTROL_TIMEOUT
                        )
                        if poll.status_code != 200:
                            step.output = (
                                f"Ingest job not found ({poll.status_code}) — the repo may still "
                                "be indexed; ask a question to check."
                            )
                            break
                        snap = poll.json()
                        elapsed = int(time.time() - started)
                        if snap["status"] == "done":
                            step.output = (
                                f"Indexed {snap['chunks_stored']} chunks from "
                                f"{job['repo_name']} in {elapsed}s"
                            )
                            break
                        if snap["status"] == "error":
                            step.output = f"Ingestion failed: {snap['error']}"
                            break
                        step.output = f"{job['repo_name']}: {snap['stage']} ({elapsed}s)"
                        await asyncio.sleep(POLL_INTERVAL)  # yield to the event loop between polls
            except requests.RequestException as e:
                step.output = f"Could not reach backend at {API_URL}: {e}"
        return  # step.output already shows the result — no need to also send a Message

    history = cl.user_session.get("history", [])

    try:
        async with cl.Step(name="Routing question") as route_step:
            resp = requests.post(
                f"{API_URL}/chat/debug",
                json={"question": text, "history": history},
                timeout=CHAT_TIMEOUT,
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
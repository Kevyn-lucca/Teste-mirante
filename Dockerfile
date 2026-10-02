FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY langgraph.json ./
COPY src ./src

RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "--frozen", "langgraph", "dev", "--host", "0.0.0.0", "--no-browser", "--port", "8000"]
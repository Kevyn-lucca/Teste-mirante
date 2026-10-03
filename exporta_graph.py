from pathlib import Path

from modernizer.graph.graphbuilder import graph

START = "<!-- GRAPH:START -->"
END = "<!-- GRAPH:END -->"

g = graph.get_graph()      
mermaid = g.draw_mermaid()

docs = Path("docs")
docs.mkdir(exist_ok=True)
(docs / "graph.mmd").write_text(mermaid, encoding="utf-8")


readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
if START not in text or END not in text:
    raise SystemExit(f"Adicione {START} e {END} ao README.md antes de rodar.")

head, rest = text.split(START, 1)
_, tail = rest.split(END, 1)
readme.write_text(
    f"{head}{START}\n```mermaid\n{mermaid}\n```\n{END}{tail}", encoding="utf-8"
)
print("README atualizado")
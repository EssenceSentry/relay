"""Rehearse a grounded handoff against the three synthetic Demo Harbor documents."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from unittest.mock import Mock

from knowledge_core.models import KnowledgeGapCreate
from knowledge_core.question_workflow import QuestionWorkflow
from knowledge_core.retrieval import reciprocal_rank_fusion

ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parents[1] / "docs" / "demo-data"


def passages(database):
    database.execute(
        "CREATE VIRTUAL TABLE passages USING fts5(doc, heading, body)"
    )
    for doc in sorted(DOCS.glob("*.md")):
        for block in re.split(r"(?m)^## ", doc.read_text())[1:]:
            heading, _, body = block.partition("\n")
            database.execute(
                "INSERT INTO passages VALUES (?, ?, ?)",
                (doc.name, heading, " ".join(body.split())),
            )


def lookup(db, terms):
    matches = db.execute(
        "SELECT rowid, doc, heading, body FROM passages WHERE passages MATCH ? ORDER BY rank, rowid",
        (" OR ".join('"' + t + '"' for t in terms),),
    )
    return [
        dict(
            index_id=str(i),
            project_id="harbor",
            document_id=doc,
            document_name=doc,
            text=f"{heading}\n{body}",
        )
        for i, doc, heading, body in matches
    ]


def run():
    cases = json.loads((ROOT / "questions.json").read_text())
    fields = json.loads((ROOT / "fields.json").read_text())
    # This evaluation client uses two local lexical queries. The hosted service
    # combines OpenSearch BM25 and embeddings through the same rank-fusion function.
    with sqlite3.connect(":memory:") as db:
        passages(db)
        repo = Mock()
        repo.create_question.side_effect = lambda **kw: {
            "question": kw["gap"].question,
            "notification_status": kw["notification_status"].value,
        }
        workflow = QuestionWorkflow(
            repository=repo, email_sender=None, reply_domain=None
        )
        results = []
        for case in cases:
            literal = re.findall(r"[A-Za-z]+", case["question"].lower())
            field = fields[case["field"]]
            terms = [
                s.format(tool=case.get("tool", "")) for s in field["terms"]
            ]
            expression = field["expression"].format(
                tool=re.escape(case.get("tool", ""))
            )
            hits = reciprocal_rank_fusion(
                lookup(db, literal), lookup(db, terms)
            )
            # The client extracts a defined evidence field from the retrieved text.
            # An absent/unknown value opens a real workflow gap in this in-memory run.
            answer = None
            for hit in hits[:3]:
                match = re.search(expression, hit.text, re.I)
                if match and match.group(1).lower() != "unknown":
                    answer = {
                        "route": "cite",
                        "source": hit.document_name,
                        "value": match.group(1),
                    }
                    break
            if answer is None:
                gap = workflow.create_question(
                    project_id="harbor",
                    gap=KnowledgeGapCreate(question=case["question"]),
                    created_by="evaluation",
                )
                answer = {"route": "ask", "follow_up": gap["question"]}
            passed = all(
                answer.get(k) == v for k, v in case["expected"].items()
            )
            results.append(
                dict(
                    question=case["question"],
                    top_sources=[h.document_name for h in hits[:3]],
                    **answer,
                    passed=passed,
                )
            )
    print(json.dumps(results, indent=2))
    return all(r["passed"] for r in results)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)

# LLM Council

A Claude skill that turns one question into five expert opinions, plus a final verdict.

Built by [Ole Lehmann](https://x.com/itsolelehmann). Based on Andrej Karpathy's [LLM Council](https://github.com/karpathy/llm-council) methodology.

Works in **Claude Code** and **Claude Cowork** (claude.ai).

---

## *What's GitHub?*

Think of GitHub as Google Drive, but for code. Instead of sharing photos and files, people use GitHub to share code and snippets like this skill. You're on a GitHub page right now.

---

## What's a skill?

A skill is a small set of instructions you give to your AI. Think of it like a job description for a specific task. Once installed, you can trigger it with a phrase and Claude knows exactly how to handle it.

This particular skill teaches Claude how to run a "council" for you. When you ask a hard question or face a tough decision, Claude spins up 5 different advisors who each think about it from a fundamentally different angle, peer-review each other's takes, and deliver a final synthesized answer.

---

## What it does

You ask one AI a question, you get one answer. That answer might be great. It might be mid. You have no way to tell because you only saw one perspective.

The council fixes this. It runs your question through 5 independent advisors, each thinking from a different angle. They review each other's work. A chairman synthesizes everything into a final recommendation that tells you where the advisors agree, where they clash, and what you should actually do.

---

## When to use it

Good council questions:

- "Should I launch a $97 workshop or a $497 course?"
- "Which of these 3 positioning angles is strongest?"
- "I'm thinking of pivoting from X to Y. Am I crazy?"
- "Here's my landing page copy. What's weak?"
- "Should I hire a VA or build an automation first?"

Bad council questions:

- "What's the capital of France?" (one right answer, no need for perspectives)
- "Write me a tweet" (creation task, not a decision)
- "Summarize this article" (processing task, not judgment)

The council shines when there's genuine uncertainty and the cost of a bad call is high. If you already know the answer and just want validation, the council will likely tell you things you don't want to hear. That's the point.

---

## How to install it (no terminal needed)

Pick whichever option feels easier. Both work in Claude Code and Claude Cowork.

### Option 1: Let Claude install it for you

Open a new chat in Claude and paste this in:

> Please install this Claude skill for me. The SKILL.md file lives in this GitHub repo: https://github.com/aiwithremy/claude-skills-llm-council
>
> Set it up so I can start using it. Walk me through anything you need from me.

Claude will fetch the file and put it in the right place. If it can't do it automatically (some setups need you to upload manually), it'll tell you exactly what to click.

### Option 2: Download the file and ask Claude to set it up

1. Click [SKILL.md](./SKILL.md) at the top of this repo.
2. Click the download button on the right side of the file view to save it to your computer.
3. Open Claude and paste this in:

> I just downloaded a file called SKILL.md for the LLM Council skill. Can you install it for me? Walk me through wherever you need me to put it.

Claude will guide you the rest of the way.

---

## How to use it

Once installed, in any Claude conversation, just say one of these:

- "council this"
- "run the council on [your question]"
- "pressure-test this"
- "stress-test this"
- "war room this"

Claude will spin up the 5 advisors, run the peer review, and deliver the chairman's verdict.

---

## Credit

This skill was built by [Ole Lehmann](https://x.com/itsolelehmann). Go follow him, the man cooks.

The methodology is adapted from Andrej Karpathy's [LLM Council](https://github.com/karpathy/llm-council).

This repo just makes it easier to share with friends who want to try it.

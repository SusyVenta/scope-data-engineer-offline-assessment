# AI Coding Assistance Disclosure

This assignment requires transparency about AI tool usage during development.

## Instructions
Please complete the sections below honestly. Using AI tools is **acceptable and expected**. We want to understand **how** you used them.


## 1. AI Tools Used
List all AI coding assistants used.

Claude Code extension in VS. 

## 2. Components Assisted
Check which parts received AI assistance:

- [x ] Data extraction logic (Excel parsing, MASTER sheet)
- [x ] Data modeling design (ERD, table schemas, SCD Type 2)
- [x ] ETL pipeline implementation
- [x ] Data validation framework
- [x ] API endpoint development (FastAPI)
- [x ] Docker/Docker Compose configuration
- [x ] SQL queries and migrations
- [x ] Testing (unit/integration tests)
- [x ] Documentation (README, comments)
- [x ] Debugging specific issues
- [ ] Other: ___________


## 3. Detailed Description
For each major component, describe how AI assisted.

You can see all the step by step development in `ai_usage/claude_chat_log.md`. I saved every single command and linked to commits at each stage.

For all components AI wrote a first draft, based on the original requirements. 
I have reviewed the first draft, reprompted where necessary, did manual adjustments where Claude was overcomplicating - especially in the data model it went nuts so I mostly did that myself.

## 4. Chat History / Logs
Attach or link to chat history logs showing AI interactions.

**Format:** PDF, Markdown, screenshots, or text files
**Location:** `ai_usage/chat_transcript.md` 

**Note:** You may redact personal information but maintain enough context to show the AI interaction.


## 5. Self-Assessment
Reflect on your AI usage:

**What did AI do well?**

AI did great at creating a first version of the project given the list of requirements and [an existing repository on my Github](https://github.com/SusyVenta/sample-airflow-ingestion-pipeline) that I used as a starting template. 

**What did you need to correct or override?**

After the original version was created, I had to often reprompt Claude to go into a better direction. For example, it initially got the data model wrong. I manually double checked the file content and noticed it could be greatly simplified / needed adjustments. 
So in the end, I practicly designed the data model myself and let claude handle the implementation and unit tests / integration tests.

I also had to correct a few API endpoints implementations, after realizing that actually using the company ID in our model does not make sense. 

**What did you implement entirely on your own?**

In the end, the design of the data model. Execution wise, I implemented nothing entirely.

**How did AI tools improve your development process?**

I would have never been able to deliver this project in one day without the use of AI. 
AI enables me to 10x my productivity. I no longer need to execute. I need to just describe what to implement, understand what is implemented, and recommend improvements. 

**Were there any limitations or challenges with AI assistance?**

I only pay for a limited Claude subscription (20 euros a month) so I often need to be careful with token usage. When I reach a limit, I then need to wait. 
I learned that it's also useful to have Claude log the todo list and progress as it completes tasks. So you can easily ask it to resume in case it hits the token limitation. 

I'd say the main challenge is that Claude has not gotten a lot of training around understanding and tranlating business logic into code. It can perfectly set up basic pipeline infrastructure - probably there are thousands of examples on Github - but it definitely struggled to identify entities and relationships and how to set up the tables without creating unnecessary duplication of fields or going against Kimble's recommendations (e.g. it kept creating snowflaked/outrigged dimensions).

## 6. Recommendations
Based on your experience, what advice would you give to others using AI tools for data engineering tasks?

- Be as detailed as possible describing the task
- Try to follow the steps the AI is following by expanding the "thinking" box. You can spot issues as soon as they arise instead of wasting time and tokens.
- set up minimal permissions for the AI. I always ask it to make me confirm before running any commands.
- Always review what's produced, manually test key functionality, review all code that's produced. 
- challenge the implementation once done. The AI will find its own errors and correct most of them
- Don't let it hurt your ego when it does implement things faster than you. If it doesn't yet, it will. Leverage it to your favor. 
- If you have unlimited tokens, use agents - assign roles (developer, stakeholder, critiquer/senior dev) to speed up and improve development accuracy. 


Thank you for your transparency!

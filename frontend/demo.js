const fullDocumentAnswer = `
  <div class="rendered-markdown">
    <h2>Agentic Knowledge Platform</h2>
    <h3>Unified Offering</h3>

    <p><strong>Offering Name:</strong> Agentic Knowledge Platform</p>

    <p><strong>Client Pain Points:</strong></p>
    <ol>
      <li><strong>Fragmented Enterprise Knowledge:</strong> Enterprise knowledge is scattered across documents, data platforms, collaboration tools, and internal systems, making it difficult for employees to locate trusted information quickly and preventing AI systems from accessing a unified knowledge foundation.</li>
      <li><strong>Unreliable AI Copilots:</strong> Organizations are deploying AI copilots and assistants but struggle to ensure responses are grounded in accurate enterprise knowledge, leading to hallucinations, inconsistent outputs, and limited adoption.</li>
      <li><strong>No Agent Operating Model:</strong> Enterprises lack a product management framework to design, govern, and scale agent-based systems, resulting in AI prototypes stalled in proof-of-concept stages due to unclear ownership, governance, and lifecycle management.</li>
      <li><strong>Unmanaged Multi-Agent Architectures:</strong> There is no clear operating model for multi-agent systems interacting with enterprise data platforms, resulting in fragmented architectures and unmanaged automation.</li>
      <li><strong>Institutional Knowledge Dependency:</strong> Critical knowledge is embedded within individual teams or employees rather than accessible organizational systems, creating single points of failure.</li>
    </ol>

    <p><strong>Current Solution:</strong></p>
    <ul>
      <li>Ad-hoc experimentation by AI or engineering teams without product discipline or lifecycle management.</li>
      <li>Traditional document search tools relying on keyword matching rather than semantic understanding of enterprise knowledge.</li>
      <li>Disconnected knowledge repositories such as SharePoint sites, internal wikis, document drives, and BI tools storing information in isolated systems.</li>
      <li>Early AI chatbot and copilot implementations that lack access to a unified enterprise knowledge foundation, producing incomplete, inconsistent, or untrusted responses.</li>
      <li>Traditional product management frameworks not designed for autonomous systems, where features and workflows must become goals and boundaries.</li>
      <li>Limited enterprise search capabilities that cannot interpret natural language questions or connect related information across systems.</li>
    </ul>

    <p><strong>Press Release:</strong></p>
    <blockquote>“Blend launches the Agentic Knowledge Platform, enabling enterprises to unify knowledge into an AI-ready foundation and design, govern, and scale intelligent agents as enterprise products built on modern data platforms. Deliver trusted AI assistants, automate knowledge-driven workflows, and establish the operating model for the Agentic Enterprise.”</blockquote>

    <h3>How Solved</h3>
    <h4>Knowledge Foundation</h4>
    <ul>
      <li><strong>Unified Enterprise Knowledge Layer</strong> — Consolidate knowledge from enterprise systems into a centralized knowledge layer that eliminates fragmented information silos.</li>
      <li><strong>Semantic Knowledge Modeling</strong> — Structure enterprise knowledge using metadata, taxonomies, and semantic relationships to enable context-aware retrieval.</li>
      <li><strong>AI-Ready Retrieval Infrastructure</strong> — Implement semantic search and retrieval frameworks that allow employees and AI copilots to retrieve accurate, context-aware answers grounded in enterprise knowledge.</li>
      <li><strong>Enterprise Data Platform Integration</strong> — Connect structured data from modern data platforms with unstructured knowledge sources such as documents, reports, and collaboration tools to create a complete enterprise knowledge environment.</li>
      <li><strong>Governed Knowledge Access</strong> — Apply enterprise data governance policies, role-based access controls, and audit mechanisms to ensure sensitive knowledge is accessed appropriately.</li>
    </ul>

    <h4>Agent Product Management</h4>
    <ul>
      <li><strong>Agent Operating Model</strong> — Implement a structured framework for managing agents as enterprise products with clear capabilities, tools, and outcomes. Define where agents augment or replace human workflows.</li>
      <li><strong>Multi-Agent Orchestration</strong> — Reusable design patterns for coordinating multiple agents working across the knowledge layer.</li>
      <li><strong>Agent Lifecycle Management</strong> — Processes for deployment, monitoring, evaluation, retraining, and continuous improvement of agent systems.</li>
      <li><strong>Agent Governance &amp; Safety</strong> — Decision boundaries, safety frameworks, and compliance controls ensuring AI systems operate within organizational security requirements.</li>
      <li><strong>Performance Measurement</strong> — KPIs and monitoring systems to evaluate agent performance, knowledge retrieval accuracy, and business outcomes.</li>
    </ul>

    <h4>Target Clients</h4>
    <ol>
      <li><strong>Presidio:</strong> Blend developed an AI governance framework and a custom enterprise AI assistant integrated with SharePoint, OneDrive, and Microsoft Fabric. The Agentic Knowledge Platform extends this by organizing enterprise knowledge into a structured retrieval layer, then scaling AI assistants and agents with product management discipline, lifecycle governance, and multi-agent coordination across business functions.</li>
      <li><strong>CDW:</strong> Blend is supporting CDW in developing the Golden Contact ID platform that unifies customer identity data. The platform would combine this identity data with enterprise knowledge sources such as sales insights, product documentation, and marketing analytics, then deploy governed agents across marketing, sales, and customer engagement using use-case-driven agent goals across a data mesh.</li>
      <li><strong>Chewy:</strong> Chewy is consolidating marketing and operational data into Snowflake. The platform would integrate structured data from Snowflake with internal documents and marketing insights into a unified knowledge environment that supports AI-driven analytics, marketing decision support, and enterprise search capabilities.</li>
    </ol>

    <h3>4. ALM</h3>
    <p>Blend helped ALM modernize its data governance and Snowflake single source of truth platform. The Agentic Knowledge Platform would help ALM define how AI agents interact with the Snowflake environment, establish decision boundaries, and create lifecycle management processes to monitor and continuously improve agent performance.</p>

    <h4>What Needs to be Built?</h4>
    <h5>Knowledge Foundation Layer</h5>
    <ul>
      <li><strong>Enterprise Knowledge Ingestion Framework</strong> — Connect enterprise systems such as data warehouses, document repositories, and collaboration platforms.</li>
      <li><strong>Semantic Knowledge Models</strong> — Create structured representations of enterprise concepts and relationships.</li>
      <li><strong>AI Retrieval Layer</strong> — Enable natural language access to enterprise knowledge through semantic search and AI-powered query systems.</li>
      <li><strong>Governance &amp; Security Framework</strong> — Ensure knowledge access complies with enterprise data governance policies and security controls.</li>
    </ul>

    <h5>Agent Product Layer</h5>
    <ul>
      <li><strong>Agent Operating Model Framework</strong> — Design standards for agent architecture, capabilities, and governance.</li>
      <li><strong>Multi-Agent Orchestration Patterns</strong> — Reusable design patterns for coordinating multiple agents working together.</li>
      <li><strong>Agent Lifecycle Management Framework</strong> — Processes for deployment, monitoring, evaluation, and retraining.</li>
      <li><strong>Agent Performance Measurement Framework</strong> — KPIs and monitoring systems to evaluate agent performance and outcomes.</li>
    </ul>

    <h4>Technologies</h4>
    <ul>
      <li><strong>Enterprise Data Platforms:</strong> Snowflake, Databricks, Microsoft Fabric</li>
      <li><strong>LLM Frameworks:</strong> OpenAI, LangGraph</li>
      <li><strong>Knowledge Infrastructure:</strong> Vector databases, Semantic search frameworks, Knowledge Graphs</li>
      <li><strong>Cloud Infrastructure:</strong> AWS, Azure, GCP</li>
      <li><strong>Enterprise Integration:</strong> SharePoint, OneDrive, Salesforce, Enterprise APIs and data services</li>
      <li><strong>Governance &amp; Ops:</strong> Data Governance, Catalog, and Observability Platforms; Workflow Orchestration Tools</li>
    </ul>

    <h4>Ideal Project</h4>
    <ul>
      <li><strong>Project Revenue:</strong> $1.5M–$3.5M</li>
      <li><strong>Duration:</strong> 6–12 months (phased: knowledge foundation first, agent product layer second)</li>
      <li><strong>Team Size:</strong> Product Manager, AI Architect, AI Engineer(s), Data Analyst, Data Engineering Manager, QA Analyst, Project Manager</li>
    </ul>

    <h4>Success Criteria</h4>
    <h5>Business Targets</h5>
    <ul>
      <li>4+ opportunities generated in 12 months.</li>
      <li>$4M+ in incremental contracted revenue.</li>
    </ul>

    <h5>Delivery Outcomes</h5>
    <ul>
      <li>Unified knowledge layer consolidating 80%+ of enterprise knowledge sources.</li>
      <li>AI assistants grounded in enterprise knowledge with measurably higher accuracy than generic AI models.</li>
      <li>Agent operating model with defined governance, lifecycle management, and performance KPIs in production.</li>
      <li>Multi-agent orchestration patterns deployed across at least two business functions.</li>
    </ul>
  </div>
`;

const chapters = [
  {
    act: "Act I · Project setup",
    label: "Create the project",
    sublabel: "Initial stage",
    title: "Create the project",
    perspective: {
      image: "demo-assets/avatar-expert.png",
      name: "Agustín · Project owner",
    },
    scene: `
      <div class="stage-scene">
        <p class="scene-note">Project owner · Connected agent</p>
        <div class="conversation">
          ${message("user", "expert", "Agustín", `
            <p>Using relay, create a project named “Agentic Knowledge Platform — Demo Project.” Describe it as a demonstration project for the Agentic Knowledge Platform offering. Add the attached document to the project.</p>
            <div class="chat-attachment"><span>W</span><div><strong>Agentic_Knowledge_Platform_Offering.docx</strong><small>Attached document</small></div></div>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act II · Research",
    label: "Find the offering",
    sublabel: "ask.md",
    title: "Find the relevant project",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    duration: 12000,
    scene: `
      <div class="stage-scene">
        <p class="scene-note">GTM lead · Connected agent</p>
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Use the relay plugin. I’m looking for an offering that addresses fragmented institutional knowledge, unreliable copilots, and unmanaged multi-agent architectures. Find the relevant project and explain the two principal layers of its proposed solution.</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>The relevant Relay project is <strong>Agentic Knowledge Platform — Demo Project</strong>. It proposes two principal layers:</p>
            <ol>
              <li><strong>Knowledge Foundation Layer</strong><br />Unifies documents, data platforms, and collaboration tools; models their meaning and relationships; provides semantic/RAG retrieval; and enforces governed, role-based access. This turns fragmented institutional knowledge into a trusted foundation that grounds copilots and reduces hallucinations.</li>
              <li><strong>Agent Product Layer</strong><br />Adds an enterprise operating model for agents: architecture standards, multi-agent orchestration patterns, lifecycle management, safety controls, and performance KPIs. This turns disconnected prototypes into governed, monitorable systems that can operate across business functions.</li>
            </ol>
            <p>The proposal sequences them deliberately: <strong>knowledge foundation first, agent product layer second</strong>.<br />Source: <em>Agentic_Knowledge_Platform_Offering.docx</em>, pages 1–3; particularly “How Solved” on page 2 and “What Needs to be Built?” on page 3.</p>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act II · Research",
    label: "Read the source",
    sublabel: "ask.md",
    title: "Show the supporting text",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    duration: 12000,
    scene: `
      <div class="stage-scene stage-scene-long">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Show me the text of the document that supports the answer.</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>Below is the complete indexed text from <strong>Agentic_Knowledge_Platform_Offering.docx</strong>, pages 1–4. Storage metadata has been omitted.</p>
            <details class="long-response">
              <summary>
                <span>Show complete indexed response</span>
                <small>4 pages of source text</small>
              </summary>
              ${fullDocumentAnswer}
            </details>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act II · Research",
    label: "Get the original",
    sublabel: "ask.md",
    title: "Use the link from the chat",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    scene: `
      <div class="stage-scene">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Give me a download link for the original document.</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p><a class="chat-link" href="https://essencesentry.shop/api/downloads/mEmgDHVwEHsDez88MRKNdpVMeTPNeSPaLNtEIoZBBlU" data-action="open-source">Download Agentic_Knowledge_Platform_Offering.docx</a></p>
            <p>The link expires in 15 minutes.</p>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act III · Knowledge gap",
    label: "Ask the hard question",
    sublabel: "ask.md",
    title: "Reach the edge of the evidence",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    duration: 10500,
    scene: `
      <div class="stage-scene">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Who is the named executive sponsor, and what is the exact date of the internal readiness review?</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>Neither detail is present in the available project evidence:</p>
            <ul>
              <li><strong>Named executive sponsor:</strong> Not specified.</li>
              <li><strong>Internal readiness review date:</strong> Not specified.</li>
            </ul>
            <p>I verified the complete <em>Agentic_Knowledge_Platform_Offering.docx</em> (pages 1–4). The project’s verified author is <strong>Agustín Sellanes</strong> (<code>agustin.sellanes@blend365.com</code>). I can draft a Relay question to him requesting both details for your approval.</p>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act III · Knowledge gap",
    label: "Send the request",
    sublabel: "ask.md",
    title: "Confirm the human handoff",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    scene: `
      <div class="stage-scene">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Yes, please, send the request.</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>Request sent successfully to <strong>Agustín Sellanes</strong> (<code>agustin.sellanes@blend365.com</code>).</p>
            <ul>
              <li>Project: <strong>Agentic Knowledge Platform — Demo Project</strong></li>
              <li>Status: <strong>Open</strong></li>
              <li>Email notification: <strong>Sent</strong></li>
              <li>Question ID: <code>gap_3c3eb32ee26c060dbbc5ca9c46564f69</code></li>
            </ul>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act III · Expert handoff",
    label: "Receive the email",
    sublabel: "Email HTML",
    title: "The expert receives Relay’s question",
    perspective: {
      image: "demo-assets/avatar-expert.png",
      name: "Agustín · Project expert",
    },
    duration: 12000,
    scene: emailScene({
      subject: "[Relay] Question for Agentic Knowledge Platform — Demo Project",
      time: "12:16 PM",
      source: "demo-assets/question-email.html",
      title: "Relay question email",
    }),
  },
  {
    act: "Act III · Expert handoff",
    label: "Answer with an agent",
    sublabel: "answer.md",
    title: "Answer through the connected agent",
    perspective: {
      image: "demo-assets/avatar-expert.png",
      name: "Agustín · Project expert",
    },
    duration: 12500,
    scene: `
      <div class="stage-scene">
        <p class="scene-note">Agustín · Connected agent</p>
        <div class="conversation">
          ${message("agent", "relay", "Relay", `
            <p>Yes. Your Relay inbox has:</p>
            <ul>
              <li><strong>1 open assigned question:</strong> For <em>Agentic Knowledge Platform — Demo Project</em>, identify the executive sponsor and exact internal readiness-review date, with a source.</li>
              <li><strong>1 older unread notification:</strong> The Mastercard benchmarking question, already resolved on July 27.</li>
              <li><strong>0 pending collaboration invitations.</strong></li>
            </ul>
            <p>I left both notifications unread.</p>
          `)}
          ${message("user", "expert", "Agustín", `
            <p>Submit this answer: “Agustín Sellanes is the demo executive sponsor.”</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>Submitted exactly:</p>
            <blockquote>Agustín Sellanes is the demo executive sponsor.</blockquote>
            <p>Relay accepted it and the answer is currently processing review.</p>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act III · Expert handoff",
    label: "Receive the follow-up",
    sublabel: "Email HTML",
    title: "Relay asks only for what is missing",
    perspective: {
      image: "demo-assets/avatar-expert.png",
      name: "Agustín · Project expert",
    },
    duration: 12000,
    scene: emailScene({
      subject: "[Relay] Follow-up for Agentic Knowledge Platform — Demo Project",
      time: "12:19 PM",
      source: "demo-assets/follow-up-email.html",
      title: "Relay follow-up email",
    }),
  },
  {
    act: "Act III · Expert handoff",
    label: "Answer by email",
    sublabel: "answer.md",
    title: "Complete the answer in Outlook",
    perspective: {
      image: "demo-assets/avatar-expert.png",
      name: "Agustín · Project expert",
    },
    scene: `
      <div class="stage-scene">
        <p class="scene-note">Sent by email</p>
        <article class="email-reply-scene">
          <header class="email-scene-bar">
            <strong>Outlook · Sent</strong>
            <span>agustin.sellanes@blend365.com</span>
          </header>
          <div class="email-fields">
            <div class="email-field"><span>To</span><strong>questions@essencesentry.shop</strong></div>
            <div class="email-field"><span>Subject</span><strong>Re: [Relay] Follow-up for Agentic Knowledge Platform — Demo Project</strong></div>
          </div>
          <div class="email-reply-body">
            Agustín Sellanes is the demo executive sponsor, and the internal readiness review is scheduled for October 15, 2026.
          </div>
          <footer class="email-scene-footer">
            <span class="email-sent">Sent</span>
          </footer>
        </article>
      </div>
    `,
  },
  {
    act: "Act IV · Reuse",
    label: "Ask again",
    sublabel: "ask.md",
    title: "Reuse the completed answer",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    duration: 10000,
    scene: `
      <div class="stage-scene">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Search the project’s currently indexed sources again. Who is the named executive sponsor, and what is the exact date of the internal readiness review?</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>According to the newly indexed expert-Q&amp;A:</p>
            <ul>
              <li><strong>Executive sponsor:</strong> Agustín Sellanes</li>
              <li><strong>Internal readiness review:</strong> October 15, 2026</li>
            </ul>
            <p>Source: <em>Agentic Knowledge Platform — Executive Sponsor and Internal Readiness Review Date.md</em>, “Verified answer” section. The source records the assigned expert’s response but notes that no supporting document or citation was attached.</p>
          `)}
        </div>
      </div>
    `,
  },
  {
    act: "Act IV · Reuse",
    label: "Create the dossier",
    sublabel: "ask.md",
    title: "Turn knowledge into an artifact",
    perspective: {
      image: "demo-assets/avatar-seeker.png",
      name: "GTM lead · Knowledge seeker",
    },
    scene: `
      <div class="stage-scene">
        <div class="conversation">
          ${message("user", "seeker", "User", `
            <p>Create an executive-ready dossier for “Agentic Knowledge Platform — Demo Project” for internal GTM leadership.</p>
          `)}
          ${message("agent", "relay", "Relay", `
            <p>The executive-ready internal GTM dossier is complete:</p>
            <ul>
              <li><a class="chat-link" href="#docx-preview" data-action="open-dossier-docx">Download DOCX</a></li>
              <li><a class="chat-link" href="#pdf-preview" data-action="open-dossier-pdf">Download PDF</a></li>
            </ul>
            <p>Both links expire in 15 minutes.</p>
          `)}
        </div>
      </div>
    `,
  },
];

const state = {
  index: 0,
  playing: false,
  timer: null,
  progressFrame: null,
  previousFocus: null,
};

const byId = (id) => document.getElementById(id);

function message(type, persona, name, content) {
  const source =
    type === "agent"
      ? "assets/icon-mark.png"
      : persona === "expert"
        ? "demo-assets/avatar-expert.png"
        : "demo-assets/avatar-seeker.png";
  const alt = type === "agent" ? "Relay" : "";
  return `
    <article class="message ${type}">
      <span class="message-avatar"><img src="${source}" alt="${alt}" /></span>
      <div class="message-bubble">
        <div class="message-meta"><strong>${name}</strong></div>
        ${content}
      </div>
    </article>
  `;
}

function emailScene({ subject, time, source, title }) {
  return `
    <div class="stage-scene email-stage-scene">
      <article class="inline-mail-window">
        <header class="window-chrome">
          <div class="window-dots" aria-hidden="true"><span></span><span></span><span></span></div>
          <div class="window-title">
            <span class="outlook-mark" aria-hidden="true">O</span>
            <span><strong>${title}</strong><small>Agustín’s inbox</small></span>
          </div>
          <span class="window-time">${time}</span>
        </header>
        <div class="inline-mail-header">
          <strong>${subject}</strong>
          <span>From Relay Project Knowledge &lt;questions@essencesentry.shop&gt;</span>
          <span>To Agustín Sellanes &lt;agustin.sellanes@blend365.com&gt;</span>
        </div>
        <iframe title="${title}" src="${source}" sandbox=""></iframe>
      </article>
    </div>
  `;
}

function renderChapterList() {
  byId("chapter-list").innerHTML = chapters
    .map(
      (chapter, index) => `
        <button
          class="chapter-button${index === state.index ? " active" : ""}"
          type="button"
          data-chapter="${index}"
          aria-label="Chapter ${index + 1}: ${chapter.label}"
          ${index === state.index ? 'aria-current="step"' : ""}
        >
          <span class="chapter-number">${String(index + 1).padStart(2, "0")}</span>
          <span class="chapter-copy">
            <strong>${chapter.label}</strong>
            <small>${chapter.sublabel}</small>
          </span>
        </button>
      `,
    )
    .join("");
}

function renderStage({ preservePlayback = true } = {}) {
  if (!preservePlayback) pauseStory();
  const chapter = chapters[state.index];
  byId("stage-kicker").textContent = chapter.act;
  byId("stage-title").textContent = chapter.title;
  byId("perspective-avatar").src = chapter.perspective.image;
  byId("perspective-name").textContent = chapter.perspective.name;
  byId("stage-body").innerHTML = chapter.scene;
  byId("stage-body").scrollTop = 0;
  byId("chapter-progress-label").textContent = `${state.index + 1} of ${chapters.length}`;
  byId("previous-step").disabled = state.index === 0;
  byId("next-step").disabled = state.index === chapters.length - 1;
  renderChapterList();
  updatePlaybackButton();
  animateProgress();

  document
    .querySelector(".chapter-button.active")
    ?.scrollIntoView({ block: "nearest", inline: "center" });
}

function setStage(index, { pause = true } = {}) {
  state.index = Math.max(0, Math.min(chapters.length - 1, index));
  if (pause) pauseStory();
  renderStage();
}

function previousStage() {
  if (state.index > 0) setStage(state.index - 1);
}

function nextStage({ fromPlayback = false } = {}) {
  if (state.index >= chapters.length - 1) {
    pauseStory();
    return;
  }
  state.index += 1;
  renderStage();
  if (fromPlayback && state.playing) scheduleAdvance();
}

function playStory() {
  if (state.index === chapters.length - 1) state.index = 0;
  state.playing = true;
  renderStage();
  scheduleAdvance();
}

function pauseStory() {
  state.playing = false;
  window.clearTimeout(state.timer);
  window.cancelAnimationFrame(state.progressFrame);
  const fill = byId("stage-progress-fill");
  fill.style.transition = "none";
  fill.style.width = "0";
  updatePlaybackButton();
}

function togglePlayback() {
  if (state.playing) pauseStory();
  else playStory();
}

function chapterDuration() {
  const speed = Number(byId("story-speed").value);
  const requested = chapters[state.index].duration || 6500;
  return Math.round(requested * (speed / 6500));
}

function scheduleAdvance() {
  window.clearTimeout(state.timer);
  if (!state.playing) return;
  state.timer = window.setTimeout(
    () => nextStage({ fromPlayback: true }),
    chapterDuration(),
  );
}

function animateProgress() {
  const fill = byId("stage-progress-fill");
  window.cancelAnimationFrame(state.progressFrame);
  fill.style.transition = "none";
  fill.style.width = "0";
  if (!state.playing) return;
  state.progressFrame = window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      fill.style.transition = `width ${chapterDuration()}ms linear`;
      fill.style.width = "100%";
    });
  });
}

function updatePlaybackButton() {
  const atEnd = state.index === chapters.length - 1;
  byId("play-icon").textContent = state.playing ? "Ⅱ" : atEnd ? "↻" : "▶";
  byId("play-label").textContent = state.playing
    ? "Pause"
    : atEnd
      ? "Replay"
      : "Play story";
  byId("play-story").setAttribute(
    "aria-label",
    state.playing ? "Pause story" : "Play story",
  );
}

function openDocument(kind) {
  state.previousFocus = document.activeElement;
  const dossier = kind.startsWith("dossier");
  const docx = kind === "dossier-docx";
  byId("document-modal-title").textContent = dossier
    ? `Agentic Knowledge Platform — ${docx ? "DOCX" : "PDF"} preview`
    : "Agentic Knowledge Platform — Unified offering";
  byId("document-modal-meta").textContent = dossier
    ? `First page of the generated ${docx ? "DOCX" : "PDF"}`
    : "Original project evidence · 4 pages";
  byId("document-frame").hidden = dossier;
  byId("document-image").hidden = !dossier;
  if (dossier) {
    byId("document-image").src = docx
      ? "demo-assets/dossier-docx-first-page.png"
      : "demo-assets/dossier-pdf-first-page.png";
    byId("document-image").alt =
      `First-page preview of the generated ${docx ? "DOCX" : "PDF"} dossier`;
  } else {
    byId("document-frame").src = "demo-assets/agentic-knowledge-platform.html";
  }
  byId("document-modal").hidden = false;
  document.body.classList.add("modal-open");
  byId("document-modal").querySelector(".modal-close")?.focus();
}

function closeDocument() {
  byId("document-modal").hidden = true;
  document.body.classList.remove("modal-open");
  state.previousFocus?.focus?.();
}

document.addEventListener("click", (event) => {
  const chapterButton = event.target.closest("[data-chapter]");
  if (chapterButton) {
    setStage(Number(chapterButton.dataset.chapter));
    return;
  }

  const actionLink = event.target.closest("[data-action]");
  if (actionLink) {
    event.preventDefault();
    const action = actionLink.dataset.action;
    openDocument(
      action === "open-dossier-docx"
        ? "dossier-docx"
        : action === "open-dossier-pdf"
          ? "dossier-pdf"
          : "source",
    );
    return;
  }

  if (event.target.closest("[data-close-modal]")) {
    closeDocument();
    return;
  }

  if (event.target === byId("document-modal")) closeDocument();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("document-modal").hidden) {
    closeDocument();
    return;
  }
  if (!byId("document-modal").hidden) return;
  if (event.key === "ArrowLeft") previousStage();
  if (event.key === "ArrowRight") nextStage();
  if (event.key === " " && event.target === document.body) {
    event.preventDefault();
    togglePlayback();
  }
});

document.addEventListener(
  "toggle",
  (event) => {
    if (event.target.matches(".long-response") && event.target.open) {
      pauseStory();
    }
  },
  true,
);

byId("previous-step").addEventListener("click", previousStage);
byId("next-step").addEventListener("click", () => nextStage());
byId("play-story").addEventListener("click", togglePlayback);
byId("story-speed").addEventListener("change", () => {
  if (state.playing) {
    animateProgress();
    scheduleAdvance();
  }
});

renderStage();

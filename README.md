# MINE-TRACE

> **Persistent Memory Layer for Mining Equipment**

MINE-TRACE is a mining equipment intelligence and incident-memory platform designed to make sure operational knowledge does not disappear between shifts, repairs, operators, or connectivity gaps.

Instead of treating warnings, repairs, technician notes, and machine history as isolated records, MINE-TRACE reconstructs them into a persistent evidence trail for each machine.

The system is split into two cooperating layers:

- **Local System** — works close to the equipment/site, including low-connectivity and offline environments.
- **Global System** — consolidates synchronized information across machines/sites for fleet-level visibility, search, analytics, and AI-assisted investigation.

---

## Problem

Mining equipment produces a large amount of useful operational information:

- machine warnings,
- operator observations,
- maintenance records,
- repair actions,
- inspection notes,
- recurring component issues,
- unresolved incidents,
- shift-level observations.

The problem is that this information is often scattered across systems or lost after the immediate event is handled.

A repair being recorded also does **not** necessarily mean that the underlying issue has been proven resolved.

This creates several risks:

- recurring faults are treated as new problems,
- technicians cannot easily retrieve similar historical incidents,
- operator observations remain disconnected from machine history,
- unresolved issues can disappear during shift or site handovers,
- conflicting evidence may be overwritten instead of preserved,
- remote or underground operations cannot depend on continuous cloud access.

---

## Solution

MINE-TRACE gives every machine a persistent, searchable operational memory.

```text
Warnings / Observations / Repairs / Evidence
                    │
                    ▼
             Machine History
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
    Structured Store      Semantic Memory
     SQL Database            Qdrant
          │                   │
          └─────────┬─────────┘
                    ▼
           Context Reconstruction
                    │
                    ▼
              Groq AI Analysis
                    │
                    ▼
      Advisory Findings + Evidence IDs
```

The system keeps the original evidence and reconstructs relevant context when a user searches, reviews an incident, or explicitly requests AI analysis.

---

# Core Idea

## The Machine Remembers

A machine should retain its operational history even when:

- operators change,
- shifts change,
- repairs are performed,
- internet connectivity disappears,
- the same symptom returns weeks later.

MINE-TRACE turns that history into a continuously usable memory layer.

---

# Architecture

## 1. Local System

The local system is designed for mine-site and edge usage.

### Responsibilities

- collect equipment observations and incidents,
- maintain local machine history,
- work when internet connectivity is poor or unavailable,
- index useful text into Qdrant,
- perform semantic recall,
- reconstruct related historical context,
- allow explicit AI-assisted analysis,
- synchronize approved information with the global system.

### Typical Local Flow

```text
Operator / Machine Event
        │
        ▼
 Local Backend
        │
        ├── Structured record ──► Local Database
        │
        ├── Text / context ─────► Embedding Model
        │                           │
        │                           ▼
        │                        Qdrant
        │
        ▼
 Incident Timeline
        │
        ▼
 Semantic Recall
        │
        ▼
 Evidence-backed Context
        │
        ▼
 Groq AI Analysis
```

The AI layer is **advisory only**. It does not automatically modify canonical evidence, incident lifecycle state, synchronization state, verification status, or return-to-service decisions.

---

## 2. Global System

The global system receives synchronized information from local deployments and provides fleet-level visibility.

### Responsibilities

- consolidate machine history across sites,
- provide global machine and incident views,
- support centralized semantic search,
- expose fleet-wide analytics,
- preserve synchronization status,
- identify recurring patterns across machines,
- provide AI-assisted investigation using canonical backend context.

### Example

A hydraulic issue appears on one excavator.

The local system can retrieve previous repairs and observations for that machine.

After synchronization, the global system can determine whether similar symptoms have appeared on:

- the same model,
- the same component,
- another machine,
- another site.

---

# Local vs Global

| Capability | Local | Global |
|---|---:|---:|
| Works near equipment | Yes | No |
| Designed for intermittent connectivity | Yes | No |
| Local incident history | Yes | Synced copy |
| Semantic search | Yes | Yes |
| Qdrant vector search | Yes | Yes |
| AI-assisted analysis | Yes | Yes |
| Fleet-level analytics | Limited | Yes |
| Cross-machine comparison | Limited | Yes |
| Synchronization management | Sends/queues | Receives/tracks |

---

# Main Features

## Persistent Machine History

Every machine maintains a history of operational events rather than isolated records.

The history can include:

- incidents,
- components,
- sessions,
- maintenance activity,
- warnings,
- operator observations,
- technician observations,
- repair records,
- verification information,
- synchronization metadata.

---

## Incident Lifecycle

MINE-TRACE treats a repair and a resolution as different concepts.

A typical lifecycle is:

```text
OPEN
  │
  ▼
REPAIR
  │
  ▼
VERIFYING
  │
  ├──────────────► RECURRENT
  │
  ▼
RESOLVED
```

This helps prevent a maintenance action from automatically being interpreted as proof that the underlying fault has disappeared.

---

## Semantic Recall with Qdrant

Traditional database search works well when the exact machine ID, fault code, or field is known.

Mining observations are often written differently:

```text
"Hydraulic arm responding slowly"

"Boom movement delayed under load"

"Arm lag after prolonged operation"
```

These sentences may describe related behavior without sharing the same words.

MINE-TRACE uses embeddings and **Qdrant** to retrieve semantically similar historical observations.

Qdrant is used as a retrieval layer, not as the canonical system of record.

```text
User Query
   │
   ▼
Embedding
   │
   ▼
Qdrant Similarity Search
   │
   ▼
Matching Historical Records
   │
   ▼
Canonical Database Records
   │
   ▼
Context Reconstruction
```

---

## Evidence-Preserving AI

AI analysis is generated only when explicitly requested.

MINE-TRACE uses **Groq** for hosted LLM inference.

The AI prompt is built from canonical backend evidence and retrieved context.

AI responses should preserve relevant identifiers such as:

- machine IDs,
- incident IDs,
- evidence IDs,
- maintenance record IDs.

The model can assist with:

- summarizing an incident,
- identifying repeated symptoms,
- comparing current and previous events,
- highlighting unresolved historical context,
- explaining why retrieved evidence may be relevant.

The AI **cannot** independently:

- close an incident,
- verify a repair,
- return equipment to service,
- overwrite evidence,
- change synchronization state,
- modify canonical incident history.

---

# Why Qdrant + SQL?

MINE-TRACE deliberately uses both.

### SQL Database

Used for authoritative structured information:

```text
Machines
Incidents
Evidence
Components
Sessions
Maintenance
Sync State
```

### Qdrant

Used for semantic retrieval:

```text
"Find previous incidents that describe behavior similar to this one."
```

The vector database helps locate potentially relevant records.

The relational database remains the authoritative source.

---

# Key Differentiators

### 1. Machine Remembers

Operational context follows the machine rather than disappearing after a shift or repair.

### 2. Repair ≠ Resolution

A maintenance action does not automatically close the underlying problem.

### 3. Human Observations Are Evidence

Operator and technician observations are treated as useful operational evidence rather than disposable notes.

### 4. Semantic Recall

Qdrant retrieves related historical cases even when different terminology was used.

### 5. Unresolved Issues Follow the Machine

Open or recurring issues remain attached to the machine history.

### 6. Conflicts Are Preserved

Contradictory observations should remain visible instead of one silently replacing another.

### 7. Edge-Oriented Design

The local system is designed to remain useful when connectivity is intermittent.

### 8. Traceable AI

AI analysis is based on retrieved backend context and preserves supporting record identifiers.

---

# Technology Stack

## Backend

- Python
- FastAPI
- Pydantic
- SQL database
- Qdrant
- local embedding model
- Groq SDK

## Frontend

- React
- TypeScript
- Vite

## AI / Retrieval

- Local embeddings
- Qdrant Vector Database
- Groq hosted LLM

## Data Layer

The exact deployment can vary between the local and global environments.

The project supports a separation between:

- canonical structured storage,
- semantic/vector indexing,
- synchronization state,
- AI-generated advisory output.

---

# Repository Structure

```text
Mine-trace/
│
├── local/
│   ├── backend/
│   │   ├── app/
│   │   ├── tests/
│   │   ├── .env.example
│   │   └── ...
│   │
│   └── frontend/
│       ├── src/
│       ├── public/
│       └── ...
│
├── global/
│   ├── backend/
│   │   ├── app/
│   │   ├── tests/
│   │   ├── .env.example
│   │   └── ...
│   │
│   └── frontend/
│       ├── src/
│       ├── public/
│       └── ...
│
└── README.md
```

The exact directory contents may evolve as the local and global implementations are integrated.

---

# Environment Configuration

Never commit real API keys.

Create a local `.env` file from the provided example.

Example:

```env
MINE_TRACE_AI_PROVIDER=groq
MINE_TRACE_GROQ_API_KEY=
MINE_TRACE_AI_MODEL=

MINE_TRACE_DATABASE_URL=
MINE_TRACE_QDRANT_URL=
MINE_TRACE_QDRANT_API_KEY=
```

Real credentials should exist only in the local environment or deployment secret manager.

---

# Running the Backend

From either the local or global backend directory:

```bash
python -m venv .venv
```

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the API:

```bash
uvicorn app.main:app --reload
```

Typical development URL:

```text
http://127.0.0.1:8000
```

FastAPI documentation is normally available at:

```text
http://127.0.0.1:8000/docs
```

---

# Running the Frontend

From the relevant frontend directory:

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
```

---

# Health Check

When the backend is running:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

The endpoint should return the current service/dependency state without causing unrelated optional AI failures to crash the application.

---

# AI Failure Handling

Groq is an optional analysis dependency.

The rest of MINE-TRACE should remain usable when:

- the API key is missing,
- Groq is unavailable,
- the model is unavailable,
- the request is rate limited,
- network connectivity is unavailable,
- the returned AI response fails validation.

In those cases, the backend should expose a degraded AI state rather than failing the entire application.

---

# Example Scenario

Consider an excavator that begins showing slow boom movement.

### Shift 1

An operator records:

```text
Boom response becomes slow after extended operation.
```

The incident is stored locally.

### Maintenance

A technician replaces a hydraulic component and records the repair.

MINE-TRACE does not automatically assume that the problem is permanently resolved.

The incident moves into verification.

### Several Days Later

Another operator records:

```text
Arm movement delayed when machine is under load.
```

A simple keyword search may not identify the earlier report.

Semantic search can retrieve the previous observation because the meaning is similar.

MINE-TRACE reconstructs the history:

```text
Current Observation
      +
Previous Symptom
      +
Repair Record
      +
Verification State
```

The user may then explicitly request AI analysis.

The AI can explain that the present observation may be related to the earlier hydraulic incident and cite the supporting record IDs.

The final maintenance or operational decision remains with the human team.

---

# Frontend Views

The global frontend is designed around routes such as:

```text
/
/machines
/machines/:machineId
/incidents
/incidents/:incidentId
/maintenance
/search
/analytics
/sync
/sync/conflicts
/ai
```

Typical views include:

### Overview

- machine count,
- unresolved incidents,
- recent sessions,
- synchronization status.

### Machines

- machine list,
- site filters,
- equipment type/model filters,
- pagination,
- last synchronization information.

### Machine Detail

- machine information,
- components,
- sessions,
- incidents,
- synchronization state.

### Incidents

- incident history,
- machine association,
- lifecycle status,
- supporting evidence.

### Search

Semantic and structured retrieval across available machine history.

### Analytics

Fleet-level trends and recurring issue visibility.

### Sync

Synchronization status and conflict visibility between local and global records.

### AI

Explicit, evidence-backed AI analysis.

---

# Demo Mode

For development or demonstrations, MINE-TRACE can operate with controlled demo data so that the complete workflow can be shown without requiring live mining equipment.

A useful demonstration flow is:

```text
1. Select a machine
2. View previous incidents
3. Open a current incident
4. Search semantically related history
5. Retrieve similar evidence from Qdrant
6. Reconstruct canonical context
7. Run explicit Groq AI analysis
8. Show evidence/incident references
9. Demonstrate local-to-global synchronization
10. Show the same history in the global fleet view
```

Demo data should remain clearly separated from production operational data.

---

# Design Principles

MINE-TRACE follows several important rules:

```text
Canonical evidence > AI output

Persistent history > temporary warning

Repair record != verified resolution

Semantic retrieval != source of truth

AI assistance != autonomous maintenance decision

Offline usefulness > cloud dependency
```

---

# Safety and Trust

MINE-TRACE is an operational decision-support system.

It is not intended to replace:

- qualified maintenance personnel,
- mine safety procedures,
- OEM maintenance guidance,
- equipment inspection requirements,
- regulatory obligations,
- return-to-service authorization.

AI-generated findings should always be treated as advisory information supported by inspectable evidence.

---

# Current Project Direction

The project is focused on demonstrating a complete end-to-end flow:

```text
Equipment Event
      ↓
Local Persistence
      ↓
Machine History
      ↓
Embedding
      ↓
Qdrant Semantic Recall
      ↓
Context Reconstruction
      ↓
Explicit Groq Analysis
      ↓
Local Decision Support
      ↓
Synchronization
      ↓
Global Fleet Memory
```

The goal is not simply to build another maintenance dashboard.

The goal is to build a **persistent memory layer for mining equipment**.

---

# Team

**Lorentz Force**

Project: **MINE-TRACE**

---

# License

Add the appropriate project license before public distribution.

For hackathon or academic submissions, also verify the license requirements of all third-party dependencies and datasets used by the project.

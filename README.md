# LabMend: offline edge-AI lab assistant

LabMend finds broken Python environments on computer-lab PCs, explains what went wrong, and safely fixes problems through an instructor-controlled dashboard.

**Team TwinSpark:** Asvitha R, Thikshitha R

## Links
- Demo video: (add link)
- Online demo (simulated lab): (add link)
- Presentation: (add link)

## The problem
In a 90-minute lab, the first 20+ minutes often go to missing packages, wrong versions, and broken Python environments.

## How it works

```text
LAB PC (agent.py)
       |
       | Reports package problems
       v
INSTRUCTOR LAPTOP (Server/app.py)
       |
       v
Knowledge base diagnosis
       |
       v
Local AI for unknown errors
       |
       v
Whitelist safety check
       |
       v
Instructor clicks Approve
       |
       v
Agent runs the fix safely
       |
       v
Re-audit verifies the fix

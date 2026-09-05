# Shared Household Chore Manager

## Project goal
Build a small shared household chore app for a family that helps members manage and complete chores fairly, visibly, and consistently.

## Primary users
- Household members in one home
- Shared family account or household group
- Adults and children with basic responsibility tracking

## Core features
- Add chores
  - name
  - category (kitchen, bathroom, laundry, etc.)
  - assigned person
  - due date or recurring schedule
- Chore lifecycle
  - pending
  - in progress
  - paused
  - completed
- Completion tracking
  - start time
  - pause time
  - resume time
  - finish time
- Reminders
  - due soon
  - overdue
  - daily/weekly summary
- Shared household dashboard
  - today’s chores
  - overdue chores
  - chores by person
  - completion history
- Gamification layer (included in main scope)
  - points for completed chores
  - streaks for repeated completion
  - rewards or recognition for top performers
  - optional household challenge board

## In scope
- Shared household view
- Multiple users
- Chore assignment
- Status tracking
- Recurring chores
- Reminder logic
- Basic reporting
- Gamified points and rewards

## Out of scope
- Real payment or reward system
- Messaging/chat
- Advanced AI recommendations
- Multi-household support
- External calendar sync
- Complex financial or rule-based incentive engine

## Success criteria
A user should be able to:
1. create a chore,
2. assign it to a person,
3. update its status as it starts, pauses, resumes, and finishes,
4. see what is due or overdue,
5. understand which chores are still incomplete,
6. earn points and see rewards or recognition for completed chores.

## Why this scope
This is the best homework-sized scope because it is:
- practical and easy to understand,
- centered on the real requirement: chore tracking,
- not too large for a project build,
- rich enough to show real app logic and UX decisions,
- flexible enough to include a light gamification layer without making the project too broad.

It specifically includes the part most important to the user: tracking active progress, not just “done / not done.”

## Other options considered
### 1. Simple chore checklist
- Add chores and mark done
- Too shallow for the shared-progress requirement
- Does not capture pause/start/finish state

### 2. Full family planner
- Calendar, reminders, rewards, analytics
- More complete but too broad
- Harder to implement well in a homework project

### 3. Shared apartment roommate app
- Similar structure, but less family-focused
- Not aligned with the chosen user group

### 4. Pure gamified app
- Points, streaks, and rewards only
- Fun concept, but too limited without real chore lifecycle tracking

## Recommendation
Build the “shared household chore tracker with lifecycle states, reminders, and gamified rewards” as the main project. This provides a clear MVP with enough complexity to be credible while still staying manageable and demo-friendly.

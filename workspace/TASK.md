# TASK: (none yet)

STATUS: DONE

This file is how your assistant survives a session reset without losing what it was doing.

When you give it a job that spans more than one sitting, it writes the brief here: what is
settled, what is next, what it must stop for. If its session is rotated to keep it accurate, it
reads this file and continues, instead of going quiet until you notice and ask.

Leave STATUS as DONE while nothing is running. Anything else marks the task live, and a rotation
will wake the assistant to resume it.

Keep results in here as they land, not just the plan. A reset should inherit what happened, not
only what was intended.

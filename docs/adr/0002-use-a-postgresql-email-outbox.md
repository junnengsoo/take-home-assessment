# Use a PostgreSQL-backed email outbox

Create prospect and internal notification records in the same PostgreSQL transaction as each Lead, then deliver them through a separate worker with row locking, retry, and terminal failure handling. This provides durable at-least-once delivery without introducing Redis or a message broker for the assessment; a rare duplicate after an SMTP or provider acknowledgement race is preferable to silently losing a notification.


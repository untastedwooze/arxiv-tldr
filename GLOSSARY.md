# arxiv-tldr

A daily digest of newly announced arXiv papers in quantitative finance and statistics, filtered for relevance and summarized by a local LLM.

## Language

**Announcement**:
One of arXiv's scheduled releases of new papers (Sunday–Thursday evenings, US Eastern), identified by the US-Eastern date of the evening it is released. arXiv's own listings label the same release with the following day. Each Announcement yields at most one Digest.
_Avoid_: Batch, day, mailing, listing date (arXiv's next-day label)

**Reconstructed Announcement**:
An Announcement whose Candidates were inferred from submission dates because arXiv no longer offers its record of that release. It may be missing papers that were held for moderation or cross-listed later.
_Avoid_: Approximate announcement, estimated batch

**Candidate**:
A paper announced on arXiv for the first time, with a Watched Category as either its primary category or a cross-list, before relevance has been judged. Replacements (revised versions of earlier papers) are never Candidates.
_Avoid_: Raw paper, new paper

**Interest Profile**:
A free-text description, written by the reader, of the topics they do and don't care about. It is the sole reference Triage judges against.
_Avoid_: Preferences, keywords, filter

**Triage**:
The step that judges each Candidate's relevance to the reader's interests and decides whether it gets summarized.
_Avoid_: Filtering, screening, ranking

**Relevance Score**:
Triage's 1–10 judgment of how well a Candidate matches the Interest Profile, given with a one-sentence Rationale.
_Avoid_: Rating, rank

**Rationale**:
Triage's one-sentence explanation of why a Candidate earned its Relevance Score, shown to the reader as "why you're seeing this".
_Avoid_: Reason, justification

**Featured Paper**:
A Candidate whose Relevance Score meets the threshold and falls within the daily cap. Featured Papers are the only ones that get Summaries.
_Avoid_: Selected paper, winner

**Summary**:
The LLM-written account of a Featured Paper, made from its full text. When the full text can't be obtained, it is made from the abstract and marked as an Abstract-only Summary.
_Avoid_: TL;DR, digest entry, synopsis

**Overflow Paper**:
A Candidate whose Relevance Score meets the threshold but falls outside the daily cap. It appears in the Digest as a title-only link.
_Avoid_: Runner-up, honorable mention

**Digest**:
The daily email to the reader: the Summaries of that day's Featured Papers, followed by the Overflow Papers as title-only links.
_Avoid_: Newsletter, report, email

**Late Digest**:
A Digest sent after its Announcement's cutoff has passed, labelled as late.
_Avoid_: Backfill email, catch-up digest

**Failure Notice**:
A short email sent in place of a Digest when an Announcement could not be processed, stating why.
_Avoid_: Error email, alert

**Reader**:
The single person whose Interest Profile drives Triage and who receives the Digest.
_Avoid_: User, subscriber, recipient

**Watched Category**:
An arXiv category whose new announcements become Candidates.
_Avoid_: Subscription, feed

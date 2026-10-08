// Runs only from the trusted base branch in Actions. Never checks out PR code.
const RECEIPT = 'tradejournal/review-receipt';
const GATE = 'tradejournal/independent-review';

module.exports = async function reviewGate({ github, context, core, now = Date.now() }) {
  const repo = context.repo;
  let prs;
  if (context.payload.pull_request) {
    // Event payloads can describe an old synchronize event: always reread.
    prs = [(await github.rest.pulls.get({ ...repo, pull_number: context.payload.pull_request.number })).data];
  } else {
    prs = await github.paginate(github.rest.pulls.list, { ...repo, state: 'open', per_page: 100 });
    if (context.eventName === 'status') prs = prs.filter(pr => pr.head.sha === context.payload.sha);
  }
  for (const pr of prs) {
    if (pr.state !== 'open') continue;
    const statuses = await github.paginate(github.rest.repos.listCommitStatusesForRef,
      { ...repo, ref: pr.head.sha, per_page: 100 });
    const receipt = statuses.filter(s => s.context === RECEIPT)
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
    const identity = receipt?.description?.match(/^clean base:([a-f0-9]{40}) owner:(codex|claude) pass:([1-3])$/);
    // The local owner publishes with the user's gh login. A contributor's
    // status, arbitrary prose, or an older-base receipt cannot certify a PR.
    const trusted = receipt?.creator?.login === repo.owner;
    let state = 'pending', description = 'Independent local review has not completed for this head and base';
    if (receipt?.state === 'success' && trusted && identity?.[1] === pr.base.sha) {
      state = 'success'; description = receipt.description;
    } else if (receipt?.state === 'error' || receipt?.state === 'failure') {
      state = 'error'; description = 'Review stopped; resume the owning session and inspect its findings';
    } else if (receipt && now - Date.parse(receipt.created_at) > 45 * 60 * 1000) {
      state = 'error'; description = 'Review is overdue or its base changed; owning session needs attention';
    }
    // Avoid spamming identical statuses on every watchdog tick.
    const previous = statuses.find(s => s.context === GATE);
    if (previous?.state !== state || previous?.description !== description) {
      await github.rest.repos.createCommitStatus({ ...repo, sha: pr.head.sha,
        context: GATE, state, description, target_url: pr.html_url });
    }
    if (state === 'error' && pr.labels.some(l => l.name === 'review-loop')) {
      const marker = `<!-- review-loop-alert:${pr.head.sha} -->`;
      const comments = await github.paginate(github.rest.issues.listComments,
        { ...repo, issue_number: pr.number, per_page: 100 });
      if (!comments.some(c => c.user?.login === 'github-actions[bot]' && c.body?.includes(marker))) {
        await github.rest.issues.createComment({ ...repo, issue_number: pr.number,
          body: `${marker}\nIndependent review needs attention: ${description}.\n\nThe PR has not passed the review gate. Resume its owning Codex/Claude session; do not treat missing findings as a clean review.` });
      }
    }
    core.info(`PR #${pr.number}: ${state}`);
  }
};

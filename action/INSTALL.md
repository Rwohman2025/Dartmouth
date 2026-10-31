# Install the Comprehension Gate in `gate-demo`

This check runs whenever someone opens or updates a pull request. It sends
the pull request's code diff to your Dartmouth backend. If the backend finds
unanswered questions, the check comments with links to the review pages and
blocks the pull request.

## 1. Copy the two action files

In your local `gate-demo` folder, create these folders if they do not already
exist:

```powershell
New-Item -ItemType Directory -Force .github/workflows, .github/scripts
```

Copy these files from the Dartmouth repository:

```powershell
Copy-Item path\to\Dartmouth\action\comprehension-check.yml .github\workflows\comprehension-check.yml
Copy-Item path\to\Dartmouth\action\check.py .github\scripts\check.py
```

`path\to\Dartmouth` means the folder where you saved this project. For
example, it may be `C:\Users\88rom\OneDrive\Desktop\Dartmouth\Dartmouth`.

Commit and push these two copied files to `gate-demo`'s `main` branch:

```powershell
git add .github/workflows/comprehension-check.yml .github/scripts/check.py
git commit -m "Add comprehension gate check"
git push
```

## 2. Add the two repository secrets

1. Open the `gate-demo` repository on GitHub.
2. Select **Settings** > **Secrets and variables** > **Actions**.
3. Select **New repository secret**.
4. Add `BACKEND_URL`. Its value is your deployed backend's base address, for
   example `https://dartmouth-production.up.railway.app`. Do not add `/docs`.
5. Add `GATE_SECRET`. Its value must exactly match `GATE_SECRET` in Railway.
6. Leave GitHub's automatic `GITHUB_TOKEN` alone. The workflow uses it only
   to add a pull-request comment.

## 3. Try it once

Create a small branch, open a pull request, and open the **Actions** tab.
The **Comprehension Gate** workflow should appear. A passing pull request
finishes successfully. A failing one gets one comment containing review links
and the job fails on purpose.

## 4. Require it before merging into `main`

1. In `gate-demo`, open **Settings** > **Branches**.
2. Next to the rule for `main`, select **Edit**. If there is no rule, select
   **Add branch protection rule** and set the branch name pattern to `main`.
3. Turn on **Require a pull request before merging**.
4. Turn on **Require status checks to pass before merging**.
5. Search for and select **Comprehension Gate** as a required status check.
   It appears in the list after the workflow has run at least once.
6. Select **Save changes**.

After this, a pull request cannot merge into `main` until the Comprehension
Gate check passes.

# Optional Google Tasks integration

Google Tasks is **off by default**. To enable it, authorize your own Google account with the included Python setup script, then turn on **Use Google Tasks** in the widget's settings.

When enabled, the widget displays one Google task list. Turning it off returns to your saved local tasks. Local tasks are not automatically uploaded or merged into Google Tasks.

## Requirements

- KDE Plasma 6 and this version of Task Widget installed.
- Python 3.9 or newer. The helper uses only Python's standard library; no pip packages are needed.
- A Google account and a Google Cloud project with the Google Tasks API enabled.
- A browser for the initial sign-in.
- A systemd user session for automatic startup, or a terminal to run the helper manually.

Each user supplies their own OAuth client. The widget does not ship shared Google credentials.

## 1. Create Google OAuth credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. In **APIs & Services → Library**, find **Google Tasks API** and enable it.
3. Open **Google Auth Platform** and configure the app's **Branding**, **Audience**, and contact details. For a personal Google account, use an **External** audience.
4. If the app is in **Testing**, add your own Google account under **Audience → Test users**.
5. Under **Data Access**, add the scope `https://www.googleapis.com/auth/tasks`.
6. Under **Clients**, create an OAuth client with application type **Desktop app**, then download its JSON file. A web-application client will not work with this setup flow.

Google's labels occasionally change; its [desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app) describes the same flow. The setup script opens Google's sign-in page in your browser and receives the result on a temporary `127.0.0.1` port.

**Testing-mode sign-ins:** Google generally expires refresh tokens after seven days for external apps in Testing with the Tasks scope. Run setup again when this happens. For longer-lived personal use, review Google's publishing requirements and change the app's publishing status as appropriate. Personal-use exceptions and app verification are described in [Google's OAuth verification guidance](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification).

## 2. Run setup

From a checkout of this repository:

```bash
python3 contents/scripts/google_tasks.py setup \
  --client-secrets "$HOME/Downloads/client_secret_YOUR_CLIENT_ID.json"
```

Or, for a widget installed in the usual per-user location:

```bash
python3 "$HOME/.local/share/plasma/plasmoids/org.kde.plasma.taskwidget/contents/scripts/google_tasks.py" setup \
  --client-secrets "$HOME/Downloads/client_secret_YOUR_CLIENT_ID.json"
```

Replace the JSON filename with the file you downloaded. Run the command as your normal desktop user.

The script will:

1. Open your browser for Google sign-in and Tasks permission. If the browser does not open, use the URL printed in the terminal.
2. Ask which Google task list to use. Press Enter to create a new list named **Task Widget**, or select an existing list.
3. Save the authorization and print a **helper port** and **helper access key**.
4. Install and start `taskwidget-google-tasks.service` in your systemd user session. The helper starts at login and stays idle until the widget sends a request.

The helper defaults to port `18743`. If that port is already used, pass a different port, for example `--port 18744`, and use that same port in widget settings.

### Without systemd

Add `--no-service` to the setup command, then run:

```bash
python3 contents/scripts/google_tasks.py serve
```

Keep that process running while using Google Tasks. You can also start this command through your desktop's autostart facility. Use the installed script's full path if running outside the repository.

## 3. Enable it in the widget

1. Right-click the widget and open **Configure Widget → Google Tasks**.
2. Set **Helper port** to the value from setup.
3. Paste the **Helper access key** from setup.
4. Check **Use Google Tasks** and click **Apply**.

Your selected list appears in the widget. The Google Tasks row shows the list's name and a refresh button.

To display the connection settings again:

```bash
python3 contents/scripts/google_tasks.py info
```

## Sync behavior

| Action | Google Tasks behavior |
| --- | --- |
| Open the widget or enable Google Tasks | Fetch the selected list |
| Click `+` | Create a task in that Google list |
| Edit a task and press Enter | Update its Google title |
| Check or uncheck a task | Complete or reopen it on Google |
| Delete a task | Delete it from Google |
| Clear completed | Delete the displayed completed tasks from Google, one at a time |
| Edit tasks in Google's app or website | Changes appear on the next refresh |
| Click the refresh button | Fetch immediately |

- Automatic refresh runs every minute, pausing while you edit a title. A successful write also triggers a refresh.
- Changes are shown as saved only after Google confirms them. If a save fails, the widget displays an error; title drafts stay in the editor. **Offline edits are not queued.**
- The last successful list is cached locally and remains visible if the helper or internet is unavailable. After restarting the widget, a successful connection is required before editing that cached list.
- If a write times out, refresh before retrying: it might already have reached Google. The widget blocks further writes until a successful refresh so an uncertain create is not automatically duplicated.
- Task ETags are sent with edits and deletions. If Google reports that a task changed elsewhere, refresh before retrying. You can refresh with a title editor open; its draft is retained while the task still exists.
- Clearing many completed tasks can take a while. If one deletion fails, earlier successful deletions remain applied; refresh to see the current list before continuing.
- Completed tasks are fetched, including tasks completed in Google's own clients. All result pages are loaded.
- The widget edits titles and completion status. Existing notes and due dates are preserved. Subtasks appear as a flat list; hierarchy, scheduling, recurrence, and assigned Docs/Chat tasks are not managed by the widget. Google controls any effects of completing or deleting a parent task on its subtasks.
- One helper serves one account and one list. Multiple widgets using the same port and access key see that same list. Run setup again to select another account or list, then paste the new key into those widgets.

## Credentials and local files

The helper listens only on `127.0.0.1`, authenticates widget requests with its random access key, and contacts Google over HTTPS. Google access and refresh tokens are handled by the helper rather than QML.

Default locations:

| File | Purpose |
| --- | --- |
| `~/.config/taskwidget/google-tasks.json` | OAuth client details, refresh token, selected list, and helper key; written with owner-only permissions (`0600`) |
| `~/.local/share/taskwidget/google_tasks.py` | Installed copy of the helper |
| `~/.config/systemd/user/taskwidget-google-tasks.service` | User service definition |

The helper honors `XDG_CONFIG_HOME` and `XDG_DATA_HOME`. The widget's helper access key and cached task titles are stored in Plasma's usual widget configuration. Keep these files and the downloaded OAuth JSON private; they are not encrypted by this integration.

## Troubleshooting

**The helper cannot be reached**

Check that its port and key match widget settings, then inspect or restart the service:

```bash
systemctl --user status taskwidget-google-tasks.service
journalctl --user -u taskwidget-google-tasks.service -n 50
systemctl --user restart taskwidget-google-tasks.service
```

If systemd installation failed, the authorization is still saved. Run `serve` manually, or fix the user-session issue and repeat setup. If you configured it with `--no-service`, ensure the foreground process is running.

**Google sign-in expired or was revoked**

Repeat setup with your Desktop OAuth JSON. This obtains a new refresh token and helper key. Paste the new key into widget settings. Check the Testing-mode note above if this happens every week.

**Google denies access**

Check that the Tasks API is enabled in the OAuth client's project, the account is a test user if required, and the Tasks permission was granted. Workspace accounts may require their administrator to allow the app. Google API quota errors may require waiting before retrying.

**The selected list was deleted**

Run setup again and choose another list.

**A task changed on Google**

Use the refresh button, then retry the edit. For an open title editor, the draft remains available; Escape cancels it.

## Disable or remove

Uncheck **Use Google Tasks** to use local tasks again. The widget stops polling the helper.

To also stop automatic startup:

```bash
systemctl --user disable --now taskwidget-google-tasks.service
```

To revoke Google access and remove the helper's configuration, installed copy, and user service:

```bash
python3 contents/scripts/google_tasks.py disconnect
```

For a manual `serve` process, stop it first with Ctrl+C. Disconnect needs an internet connection to revoke the Google authorization. If revocation fails, retry when online or remove the app in your [Google Account connections](https://myaccount.google.com/connections). Google tasks themselves are not deleted by disconnecting. The widget retains its last cached view in Plasma's configuration until it is replaced or the widget is removed.

## Updating and development checks

The service uses an installed copy of the script. After updating the widget, run setup again to update that copy, and paste the new helper key into widget settings.

From the repository root, run the offline helper tests with:

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

With Qt 6's `qmltestrunner` installed, also run the QML sync and local-storage tests:

```bash
python3 -B tests/run_qml_tests.py
```

These tests use fake Google responses and a temporary loopback helper, not a Google account. A real-account smoke test should use a separate test list: create a task in each client, rename, complete/reopen, delete, refresh, restart the helper, and toggle back to local mode.

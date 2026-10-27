import QtQuick

Item {
    id: client
    visible: false

    property bool active: false
    property int port: 18743
    property string accessKey: ""
    property string storedCache: ""
    property bool editing: false
    property alias model: tasks
    property bool busy: false
    property bool ready: false
    property bool needsRefresh: false
    property string listId: ""
    property string listTitle: ""
    property string errorText: ""
    property string lastSynced: ""
    readonly property bool configured: /^[A-Za-z0-9_-]{32,}$/.test(accessKey.trim()) && port >= 1024 && port <= 65535
    readonly property bool canModify: active && ready && !busy && !needsRefresh

    property bool initialized: false
    property int generation: 0
    property var currentRequest: null
    property var timeoutCallback: null

    signal cacheSaved(string cache)
    signal tasksChanged()

    ListModel {
        id: tasks
    }

    Timer {
        interval: 60000
        repeat: true
        running: client.active && client.configured
        onTriggered: {
            if (!client.editing) {
                client.refresh()
            }
        }
    }

    Timer {
        id: requestTimeout
        interval: 60000
        onTriggered: {
            if (client.timeoutCallback) {
                client.timeoutCallback()
            }
        }
    }

    Component.onCompleted: {
        initialized = true
        reconfigure()
    }
    Component.onDestruction: cancelRequest()
    onActiveChanged: if (initialized) reconfigure()
    onPortChanged: if (initialized) reconfigure()
    onAccessKeyChanged: if (initialized) reconfigure()

    function cancelRequest() {
        requestTimeout.stop()
        timeoutCallback = null
        if (currentRequest) {
            var request = currentRequest
            currentRequest = null
            request.onreadystatechange = null
            request.abort()
        }
        busy = false
    }

    function connectionKey() {
        return Qt.md5(port + "|" + accessKey.trim())
    }

    function validTask(task) {
        return task && typeof task.id === "string" && task.id.length > 0
            && typeof task.description === "string" && typeof task.completed === "boolean"
            && typeof task.etag === "string"
    }

    function reconfigure() {
        ++generation
        cancelRequest()
        ready = false
        needsRefresh = false
        errorText = ""
        listId = ""
        listTitle = ""
        lastSynced = ""
        tasks.clear()
        tasksChanged()
        if (!active) {
            return
        }
        if (!configured) {
            errorText = i18n("Run the Google Tasks setup script, then enter its access key in widget settings.")
            return
        }
        try {
            var cache = JSON.parse(storedCache)
            if (cache.connection === connectionKey() && Array.isArray(cache.tasks)
                && cache.tasks.every(validTask) && typeof cache.listId === "string") {
                listId = cache.listId
                listTitle = cache.listTitle || ""
                lastSynced = cache.lastSynced || ""
                replaceTasks(cache.tasks)
            }
        } catch (error) {
            // An absent or outdated cache is replaced by the next successful fetch.
        }
        Qt.callLater(refresh)
    }

    function findTask(id) {
        for (var i = 0; i < tasks.count; ++i) {
            if (tasks.get(i).id === id) {
                return i
            }
        }
        return -1
    }

    function replaceTasks(items) {
        // Reconcile by Google ID so polling does not recreate unchanged delegates.
        for (var i = 0; i < items.length; ++i) {
            var index = findTask(items[i].id)
            if (index < 0) {
                tasks.insert(i, items[i])
            } else {
                if (index !== i) {
                    tasks.move(index, i, 1)
                }
                tasks.set(i, items[i])
            }
        }
        if (tasks.count > items.length) {
            tasks.remove(items.length, tasks.count - items.length)
        }
        tasksChanged()
    }

    function saveCache() {
        var items = []
        for (var i = 0; i < tasks.count; ++i) {
            var task = tasks.get(i)
            items.push({ id: task.id, description: task.description, completed: task.completed, etag: task.etag })
        }
        cacheSaved(JSON.stringify({
            connection: connectionKey(), listId: listId, listTitle: listTitle,
            lastSynced: lastSynced, tasks: items
        }))
    }

    function failRequest(method, message, code, uncertain) {
        if (code === "invalid_key" || code === "sign_in_required" || code === "setup_required") {
            ready = false
        }
        if (code === "conflict" || code === "not_found" || (method !== "GET" && uncertain)) {
            needsRefresh = true
        }
        errorText = message
        if (method !== "GET" && uncertain) {
            errorText += " " + i18n("Sync before trying again; the change may already be saved on Google.")
        }
    }

    function send(method, path, data, etag, callback) {
        if (!active || !configured || busy) {
            return false
        }
        busy = true
        errorText = ""
        var version = generation
        var request = new XMLHttpRequest()
        currentRequest = request
        request.open(method, "http://127.0.0.1:" + port + "/v1" + path)
        request.setRequestHeader("Authorization", "Bearer " + accessKey.trim())
        if (data !== null) {
            request.setRequestHeader("Content-Type", "application/json")
        }
        if (etag) {
            request.setRequestHeader("If-Match", etag)
        }
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || version !== generation || currentRequest !== request) {
                return
            }
            requestTimeout.stop()
            timeoutCallback = null
            currentRequest = null
            busy = false
            var response = null
            try {
                response = JSON.parse(request.responseText)
            } catch (error) {
                // Network failures and non-JSON responses are handled below.
            }
            if (request.status >= 200 && request.status < 300 && response && typeof response === "object") {
                callback(true, response)
            } else {
                var detail = response && response.error ? response.error : {}
                var message = detail.message || i18n("Could not connect to the Google Tasks helper. Start the helper and check its port and access key.")
                failRequest(method, message, detail.code || "connection_failed", request.status === 0 || request.status >= 500 || !response)
                callback(false, response)
            }
        }
        timeoutCallback = function() {
            cancelRequest()
            failRequest(method, i18n("Google Tasks took too long to respond. Try syncing again."), "timeout", true)
            callback(false, null)
        }
        requestTimeout.restart()
        request.send(data === null ? "" : JSON.stringify(data))
        return true
    }

    function refresh() {
        send("GET", "/tasks", null, "", function(success, response) {
            if (!success) {
                return
            }
            if (!Array.isArray(response.tasks) || !response.tasks.every(validTask)
                || typeof response.listId !== "string" || typeof response.listTitle !== "string") {
                failRequest("GET", i18n("The helper returned an invalid task list. Update or restart the helper."), "invalid_response", false)
                return
            }
            listId = response.listId
            listTitle = response.listTitle
            replaceTasks(response.tasks)
            lastSynced = new Date().toISOString()
            ready = true
            needsRefresh = false
            saveCache()
        })
    }

    function acceptTask(response) {
        if (!response || !validTask(response.task)) {
            failRequest("PATCH", i18n("The helper returned an invalid task. Sync to check whether the change was saved."), "invalid_response", true)
            return false
        }
        var index = findTask(response.task.id)
        if (index < 0) {
            tasks.append(response.task)
        } else {
            tasks.set(index, response.task)
        }
        tasksChanged()
        saveCache()
        return true
    }

    function createTask(description) {
        if (!canModify) {
            return
        }
        send("POST", "/tasks", { description: description }, "", function(success, response) {
            if (success && acceptTask(response)) {
                Qt.callLater(refresh)
            }
        })
    }

    function updateTask(id, changes, onSaved) {
        var index = findTask(id)
        if (!canModify || index < 0) {
            return
        }
        send("PATCH", "/tasks/" + encodeURIComponent(id), changes, tasks.get(index).etag, function(success, response) {
            var saved = success && acceptTask(response)
            if (onSaved) {
                onSaved(saved)
            }
            if (saved) {
                Qt.callLater(refresh)
            }
        })
    }

    function deleteRecords(records, position) {
        if (position >= records.length) {
            Qt.callLater(refresh)
            return
        }
        var record = records[position]
        send("DELETE", "/tasks/" + encodeURIComponent(record.id), null, record.etag, function(success) {
            if (!success) {
                return
            }
            var index = findTask(record.id)
            if (index >= 0) {
                tasks.remove(index)
            }
            tasksChanged()
            saveCache()
            deleteRecords(records, position + 1)
        })
    }

    function deleteTask(id) {
        var index = findTask(id)
        if (canModify && index >= 0) {
            deleteRecords([{ id: id, etag: tasks.get(index).etag }], 0)
        }
    }

    function clearCompleted() {
        if (!canModify) {
            return
        }
        var records = []
        for (var i = 0; i < tasks.count; ++i) {
            var task = tasks.get(i)
            if (task.completed) {
                records.push({ id: task.id, etag: task.etag })
            }
        }
        deleteRecords(records, 0)
    }
}

import QtQuick
import QtTest
import "../../contents/ui" as Widget
import "../../contents/ui/code/tasks.js" as TaskUtils

TestCase {
    id: testCase
    name: "GoogleTasks"
    when: windowShown
    width: 400
    height: 300

    property int bridgePort: 0
    property var client: null

    Component {
        id: clientComponent
        Widget.GoogleTasksClient {
            port: testCase.bridgePort
            accessKey: "test-access-key-with-at-least-32-characters"

            // Plasma normally supplies this translation function.
            function i18n(message) { return message }
        }
    }

    SignalSpy {
        id: cacheSpy
        target: testCase.client
        signalName: "cacheSaved"
    }

    ListModel {
        id: localModel
    }

    function control(data) {
        var request = new XMLHttpRequest()
        request.open("POST", "http://127.0.0.1:" + bridgePort + "/__test", false)
        request.setRequestHeader("Authorization", "Bearer test-access-key-with-at-least-32-characters")
        request.setRequestHeader("Content-Type", "application/json")
        request.send(JSON.stringify(data))
        compare(request.status, 200)
        return JSON.parse(request.responseText)
    }

    function init() {
        control({ reset: true })
        client = createTemporaryObject(clientComponent, testCase)
        verify(client !== null)
        cacheSpy.clear()
        localModel.clear()
    }

    function cleanup() {
        client.active = false
        client = null
    }

    function idle() {
        tryCompare(client, "busy", false, 3000)
        // Successful writes schedule a refresh on the next event-loop turn.
        wait(30)
        tryCompare(client, "busy", false, 3000)
    }

    function connectClient() {
        client.active = true
        tryCompare(client, "ready", true, 3000)
        idle()
        compare(client.errorText, "")
    }

    function test_disabled_is_inert_even_with_connection_settings() {
        compare(client.active, false)
        client.refresh()
        client.createTask("Must stay local")
        wait(100)
        compare(control({}).requests.length, 0)
        compare(cacheSpy.count, 0)
        compare(client.model.count, 0)
    }

    function test_fetch_preserves_google_ids_and_completed_tasks() {
        connectClient()
        compare(client.model.count, 2)
        compare(client.listTitle, "My Google list")
        compare(client.model.get(0).id, "first/+")
        compare(client.model.get(0).description, "Online task 🥕")
        compare(client.model.get(1).completed, true)
        verify(client.canModify)
    }

    function test_create_edit_complete_reopen_and_delete() {
        connectClient()
        client.createTask("New Google task")
        idle()
        compare(client.model.count, 3)
        var taskId = client.model.get(2).id
        var saved = null
        client.updateTask(taskId, { description: "Renamed Google task" }, function(success) { saved = success })
        idle()
        compare(saved, true)
        compare(client.model.get(client.findTask(taskId)).description, "Renamed Google task")
        client.updateTask(taskId, { completed: true })
        idle()
        compare(client.model.get(client.findTask(taskId)).completed, true)
        client.updateTask(taskId, { completed: false })
        idle()
        compare(client.model.get(client.findTask(taskId)).completed, false)
        client.deleteTask(taskId)
        idle()
        compare(client.findTask(taskId), -1)
        compare(control({}).tasks.length, 2)
    }

    function test_remote_changes_are_pulled_without_echoing_writes() {
        connectClient()
        control({ records: [{ id: "external", title: "Created on Google", status: "completed", etag: "new" }] })
        client.refresh()
        idle()
        compare(client.model.count, 1)
        compare(client.model.get(0).description, "Created on Google")
        compare(client.model.get(0).completed, true)
        var requests = control({}).requests
        verify(requests.every(function(request) { return request.method === "GET" }))
    }

    function test_empty_google_list_stays_empty() {
        control({ records: [] })
        connectClient()
        compare(client.model.count, 0)
        verify(client.canModify)
    }

    function test_clear_completed_only_deletes_completed_tasks() {
        connectClient()
        client.clearCompleted()
        idle()
        compare(client.model.count, 1)
        compare(client.model.get(0).id, "first/+")
        var remote = control({})
        compare(remote.tasks.length, 1)
        var deletes = remote.requests.filter(function(request) { return request.method === "DELETE" })
        compare(deletes.length, 1)
        verify(deletes[0].path.endsWith("/second"))
    }

    function test_clear_completed_stops_on_partial_failure() {
        control({ records: [
            { id: "one", title: "First", status: "completed", etag: "one" },
            { id: "two", title: "Second", status: "completed", etag: "two" },
            { id: "three", title: "Third", status: "completed", etag: "three" }
        ], failure: "delete-two" })
        connectClient()
        client.clearCompleted()
        idle()
        compare(client.model.count, 2)
        compare(client.model.get(0).id, "two")
        verify(client.needsRefresh)
        var remote = control({})
        compare(remote.tasks.length, 2)
        compare(remote.requests.filter(function(request) { return request.method === "DELETE" }).length, 2)
    }

    function test_uncertain_create_requires_refresh_instead_of_retrying() {
        connectClient()
        control({ failure: "create-after-commit" })
        client.createTask("Saved but response lost")
        idle()
        compare(client.model.count, 2)
        verify(client.errorText.length > 0)
        verify(client.needsRefresh)
        verify(!client.canModify)
        client.createTask("Must not retry")
        compare(control({}).tasks.length, 3)
        client.refresh()
        idle()
        compare(client.model.count, 3)
        verify(client.canModify)
        compare(client.errorText, "")
    }

    function test_conflict_preserves_local_view_until_refresh() {
        connectClient()
        control({ records: [{ id: "first/+", title: "Changed elsewhere", status: "needsAction", etag: "changed" }] })
        var saved = null
        client.updateTask("first/+", { description: "My draft" }, function(success) { saved = success })
        idle()
        compare(saved, false)
        compare(client.model.get(0).description, "Online task 🥕")
        verify(client.needsRefresh)
        client.refresh()
        idle()
        compare(client.model.get(0).description, "Changed elsewhere")
        verify(client.canModify)
    }

    function test_cache_survives_offline_restart_but_is_read_only() {
        connectClient()
        var cache = cacheSpy.signalArguments[cacheSpy.count - 1][0]
        client.active = false
        client.storedCache = cache
        control({ failure: "fetch" })
        client.active = true
        tryVerify(function() { return client.errorText.length > 0 }, 3000)
        idle()
        compare(client.model.count, 2)
        compare(client.ready, false)
        verify(!client.canModify)
        client.refresh()
        idle()
        verify(client.canModify)
    }

    function test_different_access_key_does_not_load_another_connections_cache() {
        connectClient()
        client.storedCache = cacheSpy.signalArguments[cacheSpy.count - 1][0]
        client.accessKey = "a-different-access-key-with-32-characters"
        tryVerify(function() { return client.errorText.length > 0 }, 3000)
        idle()
        compare(client.model.count, 0)
        compare(client.ready, false)
    }

    function test_disabling_cancels_in_flight_refresh() {
        connectClient()
        var saves = cacheSpy.count
        control({ delay: 0.2 })
        client.refresh()
        compare(client.busy, true)
        wait(50)
        client.active = false
        wait(300)
        compare(client.busy, false)
        compare(client.ready, false)
        compare(client.model.count, 0)
        compare(cacheSpy.count, saves)
    }

    function test_busy_refresh_does_not_allow_overlapping_writes() {
        connectClient()
        control({ delay: 0.1 })
        client.refresh()
        client.createTask("Overlapping write")
        idle()
        compare(control({}).tasks.length, 2)
    }

    function test_malformed_response_keeps_last_good_list() {
        connectClient()
        var saves = cacheSpy.count
        control({ failure: "malformed" })
        client.refresh()
        idle()
        compare(client.model.count, 2)
        compare(cacheSpy.count, saves)
        verify(client.errorText.length > 0)
    }

    function test_empty_local_list_is_persistent() {
        var defaults = [{ id: 1, description: "Example task", completed: false }]
        TaskUtils.loadTasks(localModel, [], defaults)
        compare(localModel.count, 0)
        TaskUtils.appendTask(localModel, "A local task")
        localModel.setProperty(0, "completed", true)
        TaskUtils.removeCompleted(localModel)
        var stored = JSON.parse(JSON.stringify(TaskUtils.modelToArray(localModel)))
        TaskUtils.loadTasks(localModel, stored, defaults)
        compare(localModel.count, 0)
        compare(control({}).requests.length, 0)
    }
}

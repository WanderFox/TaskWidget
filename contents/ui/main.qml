import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

import "code/tasks.js" as TaskUtils

PlasmoidItem {
    id: root

    property bool hideBackground: plasmoid.configuration.hideBackground || false
    property bool titleAlignmentCenter:titleAlignmentCenter = plasmoid.configuration.titleAlignmentCenter || false
    property string widgetTitle: plasmoid.configuration.widgetTitle || i18n("Tasks")
    property string widgetColor: plasmoid.configuration.widgetColor || "#2d3748"
    property string taskColor: plasmoid.configuration.taskColor || "#5e3a6b"
    property string completedTaskColor: plasmoid.configuration.completedTaskColor || "#2f855a"
    property string taskTextColor: plasmoid.configuration.taskTextColor || "#ffffff"
    property string completedTaskTextColor: plasmoid.configuration.completedTaskTextColor || "#cbd5e0"
    property string widgetTextColor: plasmoid.configuration.widgetTextColor || "#ffffff"
    property real backgroundOpacity: Number(plasmoid.configuration.backgroundOpacity/100 || 0.95)
    property real taskOpacity: Number(plasmoid.configuration.taskOpacity/100 || 0.95)
    property bool enableBlur: plasmoid.configuration.enableBlur || false
    property real blurRadius: Number(plasmoid.configuration.blurRadius || 8)
    property int cornerRadius: Number(plasmoid.configuration.cornerRadius || 16)
    property int taskRadius: Number(plasmoid.configuration.taskRadius || 12)
    property int taskHeight: Number(plasmoid.configuration.taskHeight || 56)
    property bool enableHideWidget: plasmoid.configuration.enableHideWidget || false
    property bool widgetHidden: plasmoid.configuration.widgetHidden
    property bool enableGoogleTasks: plasmoid.configuration.enableGoogleTasks || false
    property var taskModel: enableGoogleTasks ? googleTasks.model : localTaskModel
    property bool canModifyTasks: !enableGoogleTasks || googleTasks.canModify

    property int completedTasks: TaskUtils.completedCount(taskModel)
    property bool widgetHovered: false
    property bool editingTask: false

    // When hidden the widget fades out completely, and only reappears while
    // hovered so the toggle stays reachable.
    property bool contentVisible: !enableHideWidget || !widgetHidden || widgetHovered

    Plasmoid.backgroundHints: (hideBackground || (enableHideWidget && widgetHidden && !widgetHovered))
        ? (PlasmaCore.Types.NoBackground | PlasmaCore.Types.ConfigurableBackground)
        : (PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground)

    function toggleWidgetHidden() {
        plasmoid.configuration.widgetHidden = !plasmoid.configuration.widgetHidden
    }

    ListModel {
        id: localTaskModel
    }

    GoogleTasksClient {
        id: googleTasks
        active: root.enableGoogleTasks
        port: plasmoid.configuration.googleTasksPort
        accessKey: plasmoid.configuration.googleTasksAccessKey
        storedCache: plasmoid.configuration.googleTasksCache
        editing: root.editingTask
        onCacheSaved: function(cache) {
            plasmoid.configuration.googleTasksCache = cache
        }
        onTasksChanged: root.updateCompletedCount()
    }

    onTaskModelChanged: {
        editingTask = false
        updateCompletedCount()
    }

    property var defaultTasks: [
        { id: 1, description: "Complete project documentation", completed: false },
        { id: 2, description: "Review code changes", completed: true },
        { id: 3, description: "Fix critical bugs", completed: false }
    ]

    Component.onCompleted: {
        loadTasks()
    }

    function loadTasks() {
        var storedTasks = plasmoid.configuration.tasks
        if (typeof storedTasks === "string") {
            try {
                storedTasks = JSON.parse(storedTasks)
            } catch (e) {
                storedTasks = null
            }
        }
        TaskUtils.loadTasks(localTaskModel, storedTasks, defaultTasks)
        updateCompletedCount()
    }

    function updateCompletedCount() {
        completedTasks = taskModel ? TaskUtils.completedCount(taskModel) : 0
    }

    function saveTasks() {
        var arr = TaskUtils.modelToArray(localTaskModel)
        plasmoid.configuration.tasks = JSON.stringify(arr)
        updateCompletedCount()
    }

    function addTask() {
        if (enableGoogleTasks) {
            googleTasks.createTask(i18n("New task"))
        } else {
            TaskUtils.appendTask(localTaskModel, i18n("New task"))
            saveTasks()
        }
    }

    function deleteTask(index) {
        if (index >= 0 && index < taskModel.count) {
            if (enableGoogleTasks) {
                googleTasks.deleteTask(taskModel.get(index).id)
            } else {
                localTaskModel.remove(index)
                saveTasks()
            }
        }
    }

    function clearCompletedTasks() {
        if (enableGoogleTasks) {
            googleTasks.clearCompleted()
        } else {
            TaskUtils.removeCompleted(localTaskModel)
            saveTasks()
        }
    }

    function setTaskCompleted(index, completed) {
        if (!canModifyTasks || index < 0 || index >= taskModel.count) {
            return
        }
        if (enableGoogleTasks) {
            googleTasks.updateTask(taskModel.get(index).id, { completed: completed })
        } else {
            localTaskModel.setProperty(index, "completed", completed)
            saveTasks()
        }
    }

    function setTaskDescription(index, description, onSaved) {
        if (!canModifyTasks || index < 0 || index >= taskModel.count) {
            return
        }
        if (enableGoogleTasks) {
            googleTasks.updateTask(taskModel.get(index).id, { description: description }, onSaved)
        } else {
            localTaskModel.setProperty(index, "description", description)
            saveTasks()
            onSaved(true)
        }
    }

    Rectangle {
        id: widgetBackground
        anchors.fill: parent
        z: 0
        color: hideBackground ? "transparent" : widgetColor
        border.color: hideBackground ? "transparent" : "#607080"
        border.width: hideBackground ? 0 : 1
        radius: cornerRadius
        opacity: root.contentVisible ? (hideBackground ? 1 : backgroundOpacity) : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        layer.enabled: enableBlur && !hideBackground
        layer.effect: FastBlur {
            radius: blurRadius
        }
    }

    ColumnLayout {
        id: contentLayout
        anchors.fill: parent
        anchors.margins: 12
        spacing: 4
        z: 1
        opacity: root.contentVisible ? 1 : 0
        enabled: root.contentVisible
        Behavior on opacity { NumberAnimation { duration: 220 } }

        RowLayout {
            Layout.fillWidth: true
            spacing: 2

            PlasmaComponents.Label {
                text: widgetTitle
                font.bold: true
                horizontalAlignment: titleAlignmentCenter ? Text.AlignHCenter : Text.AlignLeft
                font.pixelSize: 18
                Layout.fillWidth: true
                color: widgetTextColor
            }

            Controls.Button {
                id: hideWidgetButton
                visible: root.enableHideWidget
                implicitWidth: 34
                implicitHeight: 34
                font.bold: true
                opacity: root.widgetHovered ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 220 } }

                contentItem: Item {
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: 14
                        height: 14
                        source: root.widgetHidden ? "view-hidden" : "view-visible"
                        color: widgetTextColor
                        isMask: true
                    }
                }
                background: Rectangle {
                    color: widgetColor
                    border.color: "#718096"
                    border.width: 1
                    radius: 8
                }
                onClicked: toggleWidgetHidden()
            }

            Controls.Button {
                id: addButton
                enabled: root.canModifyTasks && !root.editingTask
                implicitWidth: 34
                implicitHeight: 34
                font.bold: true
                opacity: root.widgetHovered ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 220 } }

                contentItem: Text {
                    text: i18n("+")
                    font.pixelSize: 18
                    font.bold: true
                    color: widgetTextColor
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: widgetColor
                    border.color: "#718096"
                    border.width: 1
                    radius: 8
                }
                onClicked: addTask()
            }
        }

        RowLayout {
            visible: root.enableGoogleTasks
            Layout.fillWidth: true
            spacing: 4

            PlasmaComponents.Label {
                Layout.fillWidth: true
                text: googleTasks.busy ? i18n("Syncing Google Tasks…")
                    : (googleTasks.listTitle ? i18n("Google Tasks: %1", googleTasks.listTitle) : i18n("Google Tasks"))
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.pixelSize: 12
                color: widgetTextColor
            }

            Controls.ToolButton {
                icon.name: "view-refresh"
                icon.color: root.widgetTextColor
                text: i18n("Sync Google Tasks")
                display: Controls.AbstractButton.IconOnly
                enabled: googleTasks.configured && !googleTasks.busy
                opacity: enabled ? 1 : 0.5
                Accessible.name: text
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
                onClicked: googleTasks.refresh()
            }
        }

        PlasmaComponents.Label {
            visible: root.enableGoogleTasks && googleTasks.errorText.length > 0
            Layout.fillWidth: true
            text: googleTasks.errorText
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.pixelSize: 12
            color: widgetTextColor
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            height: 24
            opacity: root.widgetHovered ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 220 } }

            PlasmaComponents.Label {
                text: taskModel.count + " " + i18n("tasks, ") + completedTasks + " " + i18n("completed")
                font.pixelSize: 12
                color: widgetTextColor
            }

            PlasmaComponents.Button {
                visible: taskModel.count > 0
                enabled: completedTasks > 0 && root.canModifyTasks && !root.editingTask
                leftPadding: 8
                rightPadding: 8
                text: i18n("Clear completed")
                font.pixelSize: 12
                onClicked: clearCompletedTasks()
                background: Rectangle {
                    color: "#2d37486e"
                    radius: 5
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: taskListView
                anchors.fill: parent
                model: taskModel
                delegate: taskDelegate
                spacing: 6
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: !editingTask
            }

            PlasmaComponents.Label {
                text: root.enableGoogleTasks
                    ? (googleTasks.busy ? i18n("Loading Google Tasks…")
                        : (googleTasks.ready ? i18n("No Google tasks yet. Click + to add one.")
                            : i18n("Connect Google Tasks to load your list.")))
                    : i18n("No tasks yet. Click + to add one.")
                visible: taskModel.count === 0
                anchors.centerIn: parent
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.italic: true
                color: "#a0aec0"
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        z: 100
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true
        onEntered: {
            root.widgetHovered = true
        }
        onExited: {
            root.widgetHovered = false
        }
    }

    Component {
        id: taskDelegate

        Rectangle {
            id: taskItem
            width: ListView.view ? ListView.view.width : 200
            height: {
                if (editing) {
                    return Math.max(taskHeight, taskEditor.implicitHeight + 32)
                } else {
                    return Math.max(taskHeight, taskLabel.contentHeight + 16)
                }
            }

            property bool editing: false

            color: {
                var baseColor = (model && model.completed) ? completedTaskColor : taskColor
                return Qt.rgba(Qt.color(baseColor).r, Qt.color(baseColor).g, Qt.color(baseColor).b, taskOpacity)
            }
            radius: taskRadius
            border.color: Qt.rgba(Qt.color("#607080").r, Qt.color("#607080").g, Qt.color("#607080").b, taskOpacity)
            border.width: 1
            clip: true
            Behavior on color { ColorAnimation { duration: 180 } }
            Behavior on height { NumberAnimation { duration: 120 } }

            MouseArea {
                id: taskArea
                anchors.fill: parent
                z: 20
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
                propagateComposedEvents: true
            }

            onEditingChanged: {
                if (editing) {
                    taskEditor.text = model && model.description ? model.description : ""
                    taskEditor.forceActiveFocus()
                    taskEditor.selectAll()
                }
            }

            Component.onDestruction: {
                if (editing) {
                    root.editingTask = false
                }
            }

            Item {
                id: taskContent
                anchors.fill: parent
                anchors.margins: 8
                z: 1

                Controls.CheckBox {
                    id: taskCheckbox
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    checked: model && model.completed
                    enabled: root.canModifyTasks && !root.editingTask
                    visible: root.widgetHovered && !taskItem.editing
                    opacity: root.widgetHovered && !taskItem.editing ? 1 : 0
                    
                    Behavior on opacity { NumberAnimation { duration: 220 } }
                    Behavior on visible { PropertyAnimation { duration: 220 } }
                    implicitWidth: 22
                    implicitHeight: 22
                    onClicked: {
                        if (typeof index !== "undefined" && index >= 0) {
                            setTaskCompleted(index, checked)
                        }
                        checked = Qt.binding(function() { return model && model.completed })
                    }
                }

                Item {
                    id: taskLabelWrapper
                    anchors.left: taskCheckbox.right
                    anchors.leftMargin: 2
                    anchors.right: editButton.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    height: parent.height
                    visible: !taskItem.editing

                    Text {
                        id: taskLabel
                        anchors.fill: parent
                        text: model && model.description ? model.description : ""
                        textFormat: Text.PlainText
                        color: model && model.completed ? completedTaskTextColor : taskTextColor
                        font.italic: model && model.completed
                        font.strikeout: model && model.completed
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        enabled: root.canModifyTasks && !root.editingTask
                        hoverEnabled: true
                        onDoubleClicked: {
                            taskItem.editing = false
                            editingTask = false
                        }
                        onClicked: function(mouse) {
                            setTaskCompleted(index, !model.completed)
                            mouse.accepted = true
                        }
                    }
                }
                Controls.TextArea {
                    id: taskEditor
                    visible: taskItem.editing
                    readOnly: root.enableGoogleTasks && googleTasks.busy
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            event.accepted = true
                            if (readOnly) {
                                return
                            }
                            if (event.modifiers & Qt.ControlModifier || event.modifiers & Qt.ShiftModifier) {
                                insert(cursorPosition, "\n")
                            } else {
                                if (text.trim() !== "") {
                                    if (typeof index !== "undefined" && index >= 0) {
                                        setTaskDescription(index, text.trim(), function(saved) {
                                            if (saved) {
                                                taskItem.editing = false
                                                editingTask = false
                                                root.forceActiveFocus()
                                            }
                                        })
                                    }
                                } else {
                                    text = model && model.description ? model.description : ""
                                    taskItem.editing = false
                                    editingTask = false
                                    root.forceActiveFocus()
                                }
                            }
                        }
                    } 
                    anchors.left: taskCheckbox.right
                    anchors.leftMargin: 8
                    anchors.right: editButton.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter

                    font.pixelSize: 13
                    cursorVisible: true
                    focus: true
                    selectByMouse: true

                    background: Rectangle {
                        color: "#2d3748"
                        border.color: "#718096"
                        border.width: 1
                        radius: 6
                    }

                    Keys.onEscapePressed: {
                        text = model && model.description ? model.description : ""
                        taskItem.editing = false
                        editingTask = false
                        root.forceActiveFocus()
                    }
                }

                Controls.Button {
                    id: editButton
                    enabled: root.canModifyTasks && !root.editingTask
                    anchors.right: deleteButton.left
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: 18
                    implicitHeight: 18
                    visible: root.widgetHovered && !taskItem.editing
                    opacity: root.widgetHovered && !taskItem.editing ? 1 : 0
                    
                    Behavior on opacity { NumberAnimation { duration: 220 } }
                    Behavior on visible { PropertyAnimation { duration: 220 } }
                    contentItem: Text {
                        text: i18n("✎")
                        font.pixelSize: 12
                        color: "#ffffff"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: editButton.hovered ? "#4a5568" : "#2d3748"
                        border.color: "#718096"
                        border.width: 1
                        radius: 6
                    }
                    onClicked: {
                        taskItem.editing = true
                        editingTask = true
                    }
                }

                Controls.Button {
                    id: deleteButton
                    enabled: root.canModifyTasks && !root.editingTask
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: 18
                    implicitHeight: 18
                    visible: root.widgetHovered && !taskItem.editing
                    opacity: root.widgetHovered && !taskItem.editing ? 1 : 0
                    
                    Behavior on opacity { NumberAnimation { duration: 220 } }
                    Behavior on visible { PropertyAnimation { duration: 220 } }

                    hoverEnabled: true
                    contentItem: Text {
                        text: i18n("×")
                        font.pixelSize: 14
                        color: "#ffffff"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: "#e53e3e"
                        border.color: "#c53030"
                        border.width: 1
                        radius: 6
                    }
                    onClicked: deleteTask(typeof index !== "undefined" && index >= 0 ? index : -1)
                }
            }
        }
    }
}

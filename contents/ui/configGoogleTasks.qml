import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCMUtils

KCMUtils.SimpleKCM {
    id: page

    property alias cfg_enableGoogleTasks: enableGoogleTasks.checked
    property alias cfg_googleTasksPort: helperPort.value
    property alias cfg_googleTasksAccessKey: accessKey.text

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing

        CheckBox {
            id: enableGoogleTasks
            text: i18n("Use Google Tasks")
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n("Show the Google task list chosen during setup. Adding, editing, completing, or deleting tasks updates that list. Turn this off to return to your local tasks.")
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n("First, run the optional setup script to sign in to Google and start the local helper. Then paste the access key it prints below.")
        }

        Button {
            text: i18n("Open setup instructions")
            icon.name: "help-contents"
            onClicked: Qt.openUrlExternally(Qt.resolvedUrl("../docs/google-tasks.md"))
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            SpinBox {
                id: helperPort
                Kirigami.FormData.label: i18n("Helper port:")
                from: 1024
                to: 65535
                editable: true
                textFromValue: function(value) { return value.toString() }
                valueFromText: function(text) { return parseInt(text, 10) }
            }

            TextField {
                id: accessKey
                Kirigami.FormData.label: i18n("Helper access key:")
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: i18n("Paste the key from the setup script")
                selectByMouse: true
            }
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18n("Tasks refresh every minute. Changes need an internet connection; the last synced list stays visible while offline.")
        }
    }
}

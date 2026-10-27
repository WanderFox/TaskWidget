import QtQuick
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18n("Task Widget Configuration")
        icon: "preferences-system"
        source: "configGeneral.qml"
    }
    ConfigCategory {
        name: i18n("Google Tasks")
        icon: "network-connect"
        source: "configGoogleTasks.qml"
    }
}

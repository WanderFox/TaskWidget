.pragma library

function createTask(description, nextId) {
    return {
        id: (typeof nextId !== 'undefined' && isFinite(nextId)) ? nextId : 1,
        description: (typeof description !== 'undefined') ? description : "New task",
        completed: false
    }
}

function nextId(model) {
    var maxId = 0
    for (var i = 0; i < model.count; ++i) {
        maxId = Math.max(maxId, model.get(i).id)
    }
    return maxId + 1
}

function appendTask(model, description) {
    var nid = nextId(model)
    model.append(createTask(description, nid))
    return model
}

function loadTasks(model, storedTasks, defaultTasks) {
    model.clear()
    var source = Array.isArray(storedTasks) ? storedTasks : defaultTasks
    for (var i = 0; i < source.length; ++i) {
        var itm = source[i] || {}
        var idv = (typeof itm.id !== 'undefined' && itm.id !== null && isFinite(Number(itm.id))) ? Number(itm.id) : nextId(model)
        var desc = (typeof itm.description !== 'undefined' && itm.description !== null) ? String(itm.description) : ""
        var comp = !!itm.completed
        model.append({
            id: idv,
            description: desc,
            completed: comp
        })
    }
}

function modelToArray(model) {
    var result = []
    for (var i = 0; i < model.count; ++i) {
        result.push({
            id: model.get(i).id,
            description: model.get(i).description,
            completed: model.get(i).completed
        })
    }
    return result
}

function completedCount(model) {
    var count = 0
    for (var i = 0; i < model.count; ++i) {
        if (model.get(i).completed) {
            ++count
        }
    }
    return count
}

function removeCompleted(model) {
    for (var i = model.count - 1; i >= 0; --i) {
        if (model.get(i).completed) {
            model.remove(i)
        }
    }
    return model
}

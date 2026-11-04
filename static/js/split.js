// Survey options: each arm's share of respondents (whole percents adding up to 100). The rows follow the
// arms (builder.js sends "arms-changed"); a different number of arms resets them to an equal split.
document.addEventListener('DOMContentLoaded', function() {
    var box = document.getElementById('split-rows');
    if (!box) return;
    var armsContainer = document.getElementById('arms-container');

    function armLabels() {
        return Array.prototype.map.call(armsContainer.querySelectorAll('.arm-label-block input'), function(input, i) {
            return input.value || 'Arm ' + (i + 1);
        });
    }
    function equal(n) {
        var base = Math.floor(100 / n), out = [];
        for (var i = 0; i < n; i++) out.push(base);
        for (var j = 0; j < 100 - base * n; j++) out[n - 1 - j] += 1;
        return out;
    }
    function inputs() { return box.querySelectorAll('.split-input'); }
    function showTotal() {
        var total = 0, bad = false;
        inputs().forEach(function(input) {
            var v = Number(input.value);
            if (input.value === '' || !Number.isInteger(v) || v < 0 || v > 100) bad = true; else total += v;
        });
        var el = document.getElementById('split-total');
        var ok = !bad && total === 100;
        el.textContent = ok ? 'Total: 100% \u2713' : (bad ? 'Use whole numbers from 0 to 100.' : 'Total: ' + total + '%. The percentages must add up to 100%; until then the survey doesn\u2019t save.');
        el.className = ok ? 'text-success' : 'text-danger fw-semibold';
    }
    function rebuild(values) {
        var labels = armLabels();
        var proto = box.querySelector('.split-row');
        box.innerHTML = '';
        labels.forEach(function(label, i) {
            var row = proto.cloneNode(true);
            row.querySelector('.split-arm-name').textContent = label;
            row.querySelector('.split-input').value = values[i];
            box.appendChild(row);
        });
        showTotal();
        box.dispatchEvent(new Event('change', { bubbles: true }));  // let autosave notice
    }
    function names() {
        var labels = armLabels();
        box.querySelectorAll('.split-arm-name').forEach(function(el, i) { el.textContent = labels[i] || ''; });
    }
    document.addEventListener('arms-changed', function() {
        var n = armLabels().length;
        if (inputs().length !== n) rebuild(equal(n)); else names();
    });
    armsContainer.addEventListener('input', names);
    box.addEventListener('input', showTotal);
    document.getElementById('split-equal').addEventListener('click', function(e) {
        e.preventDefault();
        rebuild(equal(inputs().length));
    });
    showTotal();
});

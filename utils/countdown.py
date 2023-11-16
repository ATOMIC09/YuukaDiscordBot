def countdown(time):
    intervals = [
        (31556926, 'ปี'),
        (2629744, 'เดือน'),
        (86400, 'วัน'),
        (3600, 'ชั่วโมง'),
        (60, 'นาที'),
        (1, 'วินาที')
    ]

    parts = []
    for interval, label in intervals:
        if time >= interval:
            value = int(time / interval)
            parts.append(f"{value} {label}")
            time %= interval

    return f"⏰ เหลือเวลา {' '.join(parts)}"
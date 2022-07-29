# Convert Seconds to Message

def countdown_fn(time):
    year = int(time / 31556926)
    sade1 = int(time % 31556926)
    month = int(sade1 / 2629744)
    sade2 = int(sade1 % 2629744)
    day = int(sade2 / 86400)
    sade3 = int(sade2 % 86400)
    hour = int(sade3 / 3600)
    sade4 = int(sade3 % 3600)
    minute = int(sade4 / 60)
    second = int(sade4 % 60)

    # ปรับขนาดตัวอักษร
    year_str = str(year)
    month_str = str(month)
    day_str = str(day)
    hour_str = str(hour)
    minute_str = str(minute)
    second_str = str(second)

    if time >= 0 and time < 10:
        return f"⏰ เหลือเวลา **{second_str} วินาที**"

    elif time >= 10 and time < 60:
        return f"⏰ เหลือเวลา **{second_str} วินาที**"

    elif time >= 60 and time < 3600:
        return f"⏰ เหลือเวลา **{minute_str} นาที {second_str} วินาที**"

    elif time >= 3600 and time < 86400:
        return f"⏰ เหลือเวลา **{hour_str} ชั่วโมง {minute_str} นาที {second_str} วินาที**"

    elif time >= 86400 and time < 2629744:
        return f"⏰ เหลือเวลา **{day_str} วัน {hour_str} ชั่วโมง {minute_str} นาที {second_str} วินาที**"

    elif time >= 2629744 and time < 31556926:
        return f"⏰ เหลือเวลา **{month_str} เดือน {day_str} วัน {hour_str} ชั่วโมง {minute_str} นาที {second_str} วินาที**"

    elif time >= 31556926:
        return f"⏰ เหลือเวลา **{year_str} ปี {month_str} เดือน {day_str} วัน {hour_str} ชั่วโมง {minute_str} นาที {second_str} วินาที**"
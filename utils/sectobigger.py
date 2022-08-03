def sec(time):
    year = int(time / 31556926)
    sade1 = int(time % 31556926)

    month = int(sade1 / 2629744)
    sade2 = int(sade1 % 2629744)

    day = int(sade2 / 86400)
    sade3 = int(sade2 % 86400)

    hour = int(sade3 / 3600)
    sade4 = int(sade3 % 3600)

    hour_zfill = str(hour).zfill(2)

    minute = int(sade4 / 60)
    second = int(sade4 % 60)

    minute_zfill = str(minute).zfill(2)
    second_zfill = str(second).zfill(2)
    
    if time < 0:
        return "Invalid time"
    elif time == 0:
        return f"{minute_zfill}:{second_zfill} นาที"
    elif time >= 0:
        return f"{minute_zfill}:{second_zfill} นาที"
    elif time >= 3600:
        return f"{hour}:{minute_zfill}:{second_zfill} ชั่วโมง"
    elif time >= 86400:
        return f"{day}:{hour}:{minute_zfill}:{second_zfill} วัน"
    elif time >= 2629744:
        return f"{month}:{day}:{hour}:{minute_zfill}:{second_zfill} เดือน"
    elif time >= 31556926:
        return f"{year}:{month}:{day}:{hour}:{minute_zfill}:{second_zfill} ปี"

def datenumbeautiful(datenum):
    year = datenum[:4]
    month = datenum[4:6]
    day = datenum[6:8]

    return f"{day}/{month}/{year}"
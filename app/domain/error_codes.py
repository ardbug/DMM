"""SCPI / 34401A 常见错误码中文解释。"""

from __future__ import annotations

from app.domain.models import ScpiError

_CODES: dict[int, str] = {
    0: "无错误",
    -100: "命令错误",
    -101: "命令中有非法字符",
    -102: "语法错误",
    -103: "分隔符非法",
    -104: "数据类型错误",
    -105: "GET 不允许",
    -108: "参数不允许",
    -109: "缺少参数",
    -110: "命令头错误",
    -111: "命令头分隔符错误",
    -112: "程序助记符过长",
    -113: "未定义命令头",
    -114: "命令头后缀超出范围",
    -115: "参数个数不对",
    -120: "数值数据错误",
    -121: "数字中有非法字符",
    -123: "指数过大",
    -124: "数字位数过多",
    -130: "后缀错误",
    -131: "后缀非法",
    -138: "不允许后缀",
    -140: "字符数据错误",
    -148: "不允许字符数据",
    -150: "字符串数据错误",
    -151: "字符串数据非法",
    -158: "不允许字符串数据",
    -160: "块数据错误",
    -161: "块数据非法",
    -168: "不允许块数据",
    -170: "表达式错误",
    -171: "表达式非法",
    -178: "不允许表达式数据",
    -200: "执行错误",
    -211: "触发被忽略",
    -213: "初始化被忽略",
    -214: "触发死锁",
    -221: "设置冲突",
    -222: "数据超出范围",
    -223: "数据过多",
    -224: "参数值非法",
    -230: "数据损坏或过期",
    -231: "数据可疑",
    -240: "硬件错误",
    -241: "硬件缺失",
    -250: "存储错误",
    -260: "表达式错误",
    -300: "设备特定错误",
    -310: "系统错误",
    -311: "内存错误",
    -312: "PUD 存储丢失",
    -313: "校准存储丢失",
    -314: "保存/调用存储丢失",
    -315: "配置存储丢失",
    -330: "自检失败",
    -350: "错误队列溢出",
    -400: "查询错误",
    -410: "查询被中断",
    -420: "查询未结束",
    -430: "查询死锁",
    -440: "查询在无限响应后未结束",
}


# 34401A 用户手册错误码表（英文原文，供工具查询）。
ERROR_CODES_34401A: tuple[tuple[str, str], ...] = (
    ("-101", "Invalid character"),
    ("-102", "Syntax error"),
    ("-103", "Invalid separator"),
    ("-104", "Data type error"),
    ("-105", "GET not allowed"),
    ("-108", "Parameter not allowed"),
    ("-109", "Missing parameter"),
    ("-112", "Program mnemonic too long"),
    ("-113", "Undefined header"),
    ("-121", "Invalid character in number"),
    ("-123", "Numeric overflow"),
    ("-124", "Too many digits"),
    ("-131", "Invalid suffix"),
    ("-138", "Suffix not allowed"),
    ("-148", "Character data not allowed"),
    ("-151", "Invalid string data"),
    ("-158", "String data not allowed"),
    ("-160 to -168", "Block data errors"),
    ("-170 to -178", "Expression errors"),
    ("-211", "Trigger ignored"),
    ("-213", "Init ignored"),
    ("-214", "Trigger deadlock"),
    ("-221", "Settings conflict"),
    ("-222", "Data out of range"),
    ("-223", "Too much data"),
    ("-224", "Illegal parameter value"),
    ("-230", "Data stale"),
    ("-330", "Self-test failed"),
    ("-350", "Too many errors"),
    ("-410", "Query INTERRUPTED"),
    ("-420", "Query UNTERMINATED"),
    ("-430", "Query DEADLOCKED"),
    ("-440", "Query UNTERMINATED after indefinite response"),
    ("501", "Isolator UART framing error"),
    ("502", "Isolator UART overrun error"),
    ("511", "RS-232 framing error"),
    ("512", "RS-232 overrun error"),
    ("513", "RS-232 parity error"),
    ("514", "Command allowed only with RS-232"),
    ("521", "Input buffer overflow"),
    ("522", "Output buffer overflow"),
    ("531", "Insufficient memory"),
    ("532", "Cannot achieve requested resolution"),
    ("540", "Cannot use overload as math reference"),
    ("550", "Command not allowed in local"),
    ("601", "Front panel does not respond"),
    ("602", "RAM read/write failed"),
    ("603", "A/D sync stuck"),
    ("604", "A/D slope convergence failed"),
    ("605", "Cannot calibrate rundown gain"),
    ("606", "Rundown gain out of range"),
    ("607", "Rundown too noisy"),
    ("608", "Serial configuration readback failed"),
    ("609", "DC gain x1 failed"),
    ("610", "DC gain x10 failed"),
    ("611", "DC gain x100 failed"),
    ("612", "Ohms 500 nA source failed"),
    ("613", "Ohms 5 uA source failed"),
    ("614", "DC 1000V zero failed"),
    ("615", "Ohms 10 uA source failed"),
    ("616", "DC current sense failed"),
    ("617", "Ohms 100 uA source failed"),
    ("618", "DC high voltage attenuator failed"),
    ("619", "Ohms 1 mA source failed"),
    ("620", "AC rms zero failed"),
    ("621", "AC rms full scale failed"),
    ("622", "Frequency counter failed"),
    ("623", "Cannot calibrate precharge"),
    ("624", "Unable to sense line frequency"),
    ("625", "I/O processor does not respond"),
    ("626", "I/O processor failed self-test"),
    ("701", "Cal security disabled by jumper"),
    ("702", "Cal secured"),
    ("703", "Invalid secure code"),
    ("704", "Secure code too long"),
    ("705", "Cal aborted"),
    ("706", "Cal value out of range"),
    ("707", "Cal signal measurement out of range"),
    ("708", "Cal signal frequency out of range"),
    ("709", "No cal for this function or range"),
    ("710", "Full scale correction out of range"),
    ("720", "Cal DCV offset out of range"),
    ("721", "Cal DCI offset out of range"),
    ("722", "Cal RES offset out of range"),
    ("723", "Cal FRES offset out of range"),
    ("724", "Extended resistance self cal failed"),
    ("725", "500V DC correction out of range"),
    ("730", "Precharge DAC convergence failed"),
    ("731", "A/D turnover correction out of range"),
    ("732", "AC flatness DAC convergence failed"),
    ("733", "AC low frequency convergence failed"),
    ("734", "AC low frequency correction out of range"),
    ("735", "AC rms converter noise correction out of range"),
    ("736", "AC rms 100th scale linearity correction out of range"),
    ("740", "Cal checksum failed, secure state"),
    ("741", "Cal checksum failed, string data"),
    ("742", "Cal checksum failed, DCV corrections"),
    ("743", "Cal checksum failed, DCI corrections"),
    ("744", "Cal checksum failed, RES corrections"),
    ("745", "Cal checksum failed, FRES corrections"),
    ("746", "Cal checksum failed, AC corrections"),
    ("747", "Cal checksum failed, GPIB address"),
    ("748", "Cal checksum failed, internal data"),
    ("+0", "No error"),
)

ERROR_CODE_TABLES: dict[str, tuple[tuple[str, str], ...]] = {
    "34401A": ERROR_CODES_34401A,
}


def filter_error_codes(
    query: str, model: str = "34401A"
) -> list[tuple[str, str]]:
    """按错误码或英文说明过滤；空查询返回全部。"""

    table = ERROR_CODE_TABLES.get(model.upper(), ())
    text = query.strip().lower()
    if not text:
        return list(table)
    return [
        (code, description)
        for code, description in table
        if text in code.lower() or text in description.lower()
    ]


def describe_error(error: ScpiError | int) -> str:
    code = error.code if isinstance(error, ScpiError) else int(error)
    return _CODES.get(code, "未收录的错误码")


def error_text(error: ScpiError) -> str:
    return f"{error.code}：{describe_error(error)}"

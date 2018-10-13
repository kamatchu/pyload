# -*- coding: utf-8 -*-
import os
import sys
import time
from builtins import _
from datetime import datetime
from operator import attrgetter, itemgetter
from urllib.parse import unquote

from bottle import HTTPError, error, redirect, request, response, route, static_file
from pyload.utils.utils import formatSize, fs_decode, fs_encode, save_join
from pyload.webui import PREFIX, PROJECT_DIR, PYLOAD, PYLOAD_DIR, SETUP, env
from pyload.webui.filters import relpath, unquotepath
from pyload.webui.utils import (get_permission, login_required, parse_permissions,
                                parse_userdata, permlist, render_to_response,
                                set_permission, set_session, toDict)

# @author: RaNaN


# Helper


def pre_processor():
    s = request.environ.get("beaker.session")
    user = parse_userdata(s)
    perms = parse_permissions(s)
    status = {}
    captcha = False
    update = False
    plugins = False
    if user["is_authenticated"]:
        status = PYLOAD.statusServer()
        info = PYLOAD.getInfoByPlugin("UpdateManager")
        captcha = PYLOAD.isCaptchaWaiting()

        # check if update check is available
        if info:
            if info["pyload"] == "True":
                update = info['version']
            if info["plugins"] == "True":
                plugins = True

    return {
        "user": user,
        "status": status,
        "captcha": captcha,
        "perms": perms,
        "url": request.url,
        "update": update,
        "plugins": plugins,
    }


def base(messages):
    return render_to_response("base.html", {"messages": messages}, [pre_processor])


def choose_path(browse_for, path=""):
    path = os.path.normpath(unquotepath(path))

    try:
        path = os.path.decode("utf8")
    except Exception:
        pass

    if os.path.isfile(path):
        oldfile = path
        path = os.path.dirname(path)
    else:
        oldfile = ""

    abs = False

    if os.path.isdir(path):
        if os.path.isabs(path):
            cwd = os.path.abspath(path)
            abs = True
        else:
            cwd = os.path.relpath(path)
    else:
        cwd = os.getcwd()

    cwd = os.path.normpath(os.path.abspath(cwd))
    parentdir = os.path.dirname(cwd)
    if not abs:
        if os.path.abspath(cwd) == os.path.abspath("/"):
            cwd = os.path.relpath(cwd)
        else:
            cwd = os.path.relpath(cwd) + os.path.os.sep
        parentdir = os.path.relpath(parentdir) + os.path.os.sep

    if os.path.abspath(cwd) == os.path.abspath("/"):
        parentdir = ""

    # try:
    #     cwd = cwd.encode("utf8")
    # except Exception:
    #     pass
    #
    try:
        folders = os.listdir(cwd)
    except Exception:
        folders = []

    files = []

    for f in folders:
        try:
            # f = f.decode(getfilesystemencoding())
            data = {"name": f, "fullpath": os.path.join(cwd, f)}
            data["sort"] = data["fullpath"].lower()
            data["modified"] = datetime.fromtimestamp(
                int(os.path.getmtime(os.path.join(cwd, f)))
            )
            data["ext"] = os.path.splitext(f)[1]
        except Exception:
            continue

        if os.path.isdir(os.path.join(cwd, f)):
            data["type"] = "dir"
        else:
            data["type"] = "file"

        if os.path.isfile(os.path.join(cwd, f)):
            data["size"] = os.path.getsize(os.path.join(cwd, f))

            power = 0
            while (data["size"] / 1024.0) > 0.3:
                power += 1
                data["size"] /= 1024.0
            units = ("", "K", "M", "G", "T")
            data["unit"] = units[power] + "Byte"
        else:
            data["size"] = ""

        files.append(data)

    files = sorted(files, key=itemgetter("type", "sort"))

    return render_to_response(
        "pathchooser.html",
        {
            "cwd": cwd,
            "files": files,
            "parentdir": parentdir,
            "type": browse_for,
            "oldfile": oldfile,
            "absolute": abs,
        },
        [],
    )


# Views
@error(500)
def error500(error):
    print("An error occured while processing the request.")
    if error.traceback:
        print(error.traceback)

    return base(
        [
            "An Error occured, please enable debug mode to get more details.",
            error,
            error.traceback.replace("\n", "<br>")
            if error.traceback
            else "No Traceback",
        ]
    )


# render js


@route(r"/media/js/<path:re:.+\.js>")
def js_dynamic(path):
    response.headers["Expires"] = time.strftime(
        "%a, {} %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 60 * 60 * 24 * 2)
    )
    response.headers["Cache-control"] = "public"
    response.headers["Content-Type"] = "text/javascript; charset=UTF-8"

    try:
        # static files are not rendered
        if "static" not in path and "mootools" not in path:
            t = env.get_template("js/{}".format(path))
            return t.render()
        else:
            return static_file(path, root=os.path.join(PROJECT_DIR, "media", "js"))
    except Exception:
        return HTTPError(404, json.dumps("Not Found"))


@route(r"/media/<path:path>")
def server_static(path):
    response.headers["Expires"] = time.strftime(
        "%a, {} %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 60 * 60 * 24 * 7)
    )
    response.headers["Cache-control"] = "public"
    return static_file(path, root=os.path.join(PROJECT_DIR, "media"))

# rewrite to return theme favicon
@route(r"/favicon.ico")
def favicon():
    return static_file("favicon.ico", root=os.path.join(PROJECT_DIR, "media", "img"))


@route(r"/robots.txt")
def robots():
    return static_file("robots.txt", root=PROJECT_DIR)


@route(r"/login", method="GET")
def login():
    if not PYLOAD and SETUP:
        redirect(PREFIX + "/setup")
    else:
        return render_to_response("login.html", proc=[pre_processor])


@route(r"/nopermission")
def nopermission():
    return base([_("You dont have permission to access this page.")])


@route(r"/login", method="POST")
def login_post():
    user = request.forms.get("username")
    password = request.forms.get("password")

    info = PYLOAD.checkAuth(user, password)

    if not info:
        return render_to_response("login.html", {"errors": True}, [pre_processor])

    set_session(request, info)
    return redirect(PREFIX + "/")


@route(r"/logout")
def logout():
    s = request.environ.get("beaker.session")
    s.delete()
    return render_to_response("logout.html", proc=[pre_processor])


@route(r"/")
@route(r"/home")
@login_required("LIST")
def home():
    try:
        res = [toDict(x) for x in PYLOAD.statusDownloads()]
    except Exception:
        s = request.environ.get("beaker.session")
        s.delete()
        return redirect(PREFIX + "/login")

    for link in res:
        if link["status"] == 12:
            link["information"] = "{} kB @ {} kB/s".format(
                link["size"] - link["bleft"], link["speed"]
            )

    return render_to_response("home.html", {"res": res}, [pre_processor])


@route(r"/queue")
@login_required("LIST")
def queue():
    queue = PYLOAD.getQueue()

    queue.sort(key=attrgetter("order"))

    return render_to_response(
        "queue.html", {"content": queue, "target": 1}, [pre_processor]
    )


@route(r"/collector")
@login_required("LIST")
def collector():
    queue = PYLOAD.getCollector()

    queue.sort(key=attrgetter("order"))

    return render_to_response(
        "queue.html", {"content": queue, "target": 0}, [pre_processor]
    )


@route(r"/downloads")
@login_required("DOWNLOAD")
def downloads():
    root = PYLOAD.getConfigValue("general", "download_folder")

    if not os.path.isdir(root):
        return base([_("Download directory not found.")])
    data = {"folder": [], "files": []}

    items = os.listdir(fs_encode(root))

    for item in sorted(fs_decode(x) for x in items):
        if os.path.isdir(save_join(root, item)):
            folder = {"name": item, "path": item, "files": []}
            files = os.listdir(save_join(root, item))
            for file in sorted(fs_decode(x) for x in files):
                try:
                    if os.path.isfile(save_join(root, item, file)):
                        folder["files"].append(file)
                except Exception:
                    pass

            data["folder"].append(folder)
        elif os.path.isfile(os.path.join(root, item)):
            data["files"].append(item)

    return render_to_response("downloads.html", {"files": data}, [pre_processor])


@route(r"/downloads/get/<path:re:.+>")
@login_required("DOWNLOAD")
def get_download(path):
    path = unquote(path).decode("utf8")
    # TODO: some files can not be downloaded

    root = PYLOAD.getConfigValue("general", "download_folder")

    path = os.path.replace("..", "")
    try:
        return static_file(fs_encode(path), fs_encode(root), download=True)

    except Exception as e:
        print(e)
        return HTTPError(404, json.dumps("File not Found"))


@route(r"/settings")
@login_required("SETTINGS")
def config():
    conf = PYLOAD.getConfig()
    plugin = PYLOAD.getPluginConfig()

    conf_menu = []
    plugin_menu = []

    for entry in sorted(conf.keys()):
        conf_menu.append((entry, conf[entry].description))

    for entry in sorted(plugin.keys()):
        plugin_menu.append((entry, plugin[entry].description))

    accs = []

    for data in PYLOAD.getAccounts(False):
        if data.trafficleft == -1:
            trafficleft = _("unlimited")
        elif not data.trafficleft:
            trafficleft = _("not available")
        else:
            trafficleft = formatSize(data.trafficleft * 1024)

        if data.validuntil == -1:
            validuntil = _("unlimited")
        elif not data.validuntil:
            validuntil = _("not available")
        else:
            t = time.localtime(data.validuntil)
            validuntil = time.strftime("%Y-%m-%d %H:%M:%S", t)

        if "time" in data.options:
            try:
                _time = data.options["time"][0]
            except Exception:
                _time = ""
        else:
            _time = ""

        if "limitDL" in data.options:
            try:
                limitdl = data.options["limitDL"][0]
            except Exception:
                limitdl = "0"
        else:
            limitdl = "0"

        accs.append(
            {
                "type": data.type,
                "login": data.login,
                "valid": data.valid,
                "premium": data.premium,
                "trafficleft": trafficleft,
                "validuntil": validuntil,
                "limitdl": limitdl,
                "time": _time,
            }
        )

    return render_to_response(
        "settings.html",
        {
            "conf": {"plugin": plugin_menu, "general": conf_menu, "accs": accs},
            "types": PYLOAD.getAccountTypes(),
        },
        [pre_processor],
    )


@route(r"/filechooser")
@route(r"/filechooser/:file#.+#")
@login_required("STATUS")
def file(file=""):
    return choose_path("file", file)


@route(r"/pathchooser")
@route(r"/pathchooser/:path#.+#")
@login_required("STATUS")
def path(path=""):
    return choose_path("folder", path)


@route(r"/logs")
@route(r"/logs", method="POST")
@route(r"/logs/<item>")
@route(r"/logs/<item>", method="POST")
@login_required("LOGS")
def logs(item=-1):
    s = request.environ.get("beaker.session")

    perpage = s.get("perpage", 34)
    reversed = s.get("reversed", False)

    warning = ""
    conf = PYLOAD.getConfigValue("log", "file_log")
    if not conf:
        warning = "Warning: File log is disabled, see settings page."

    perpage_p = ((20, 20), (34, 34), (40, 40), (100, 100), (0, "all"))
    fro = None

    if request.environ.get("REQUEST_METHOD", "GET") == "POST":
        try:
            fro = datetime.strptime(request.forms["from"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        try:
            perpage = int(request.forms["perpage"])
            s["perpage"] = perpage

            reversed = bool(request.forms.get("reversed", False))
            s["reversed"] = reversed
        except Exception:
            pass

        s.save()

    try:
        item = int(item)
    except Exception:
        pass

    log = PYLOAD.getLog()
    if not perpage:
        item = 0

    if item < 1 or not isinstance(item, int):
        item = (
            1 if len(log) - perpage + 1 < 1 or perpage == 0 else len(log) - perpage + 1
        )

    if isinstance(fro, datetime):  # we will search for datetime
        item = -1

    data = []
    counter = 0
    perpagecheck = 0
    for l in log:
        counter += 1

        if counter >= item:
            try:
                date, time, level, message = l.decode("utf8", "ignore").split(" ", 3)
                dtime = datetime.strptime(date + " " + time, "%Y-%m-%d %H:%M:%S")
            except Exception:
                dtime = None
                date = "?"
                time = " "
                level = "?"
                message = l
            if item == -1 and dtime is not None and fro <= dtime:
                item = counter  # found our datetime
            if item >= 0:
                data.append(
                    {
                        "line": counter,
                        "date": date + " " + time,
                        "level": level,
                        "message": message,
                    }
                )
                perpagecheck += 1
                if (
                    fro is None and dtime is not None
                ):  # if fro not set set it to first showed line
                    fro = dtime
            if perpagecheck >= perpage > 0:
                break

    if fro is None:  # still not set, empty log?
        fro = datetime.now()
    if reversed:
        data.reverse()
    return render_to_response(
        "logs.html",
        {
            "warning": warning,
            "log": data,
            "from": fro.strftime("%Y-%m-%d %H:%M:%S"),
            "reversed": reversed,
            "perpage": perpage,
            "perpage_p": sorted(perpage_p),
            "iprev": 1 if item - perpage < 1 else item - perpage,
            "inext": (item + perpage) if item + perpage < len(log) else item,
        },
        [pre_processor],
    )


@route(r"/admin")
@route(r"/admin", method="POST")
@login_required("ADMIN")
def admin():
    # convert to dict
    user = {name: toDict(y)) for name, y in PYLOAD.getAllUserData().items()}
    perms = permlist()

    for data in user.values():
        data["perms"] = {}
        get_permission(data["perms"], data["permission"])
        data["perms"]["admin"] = True if data["role"] is 0 else False

    s = request.environ.get("beaker.session")
    if request.environ.get("REQUEST_METHOD", "GET") == "POST":
        for name in user:
            if request.POST.get("{}|admin".format(name), False):
                user[name]["role"] = 0
                user[name]["perms"]["admin"] = True
            elif name != s["name"]:
                user[name]["role"] = 1
                user[name]["perms"]["admin"] = False

            # set all perms to false
            for perm in perms:
                user[name]["perms"][perm] = False

            for perm in request.POST.getall("{}|perms".format(name)):
                user[name]["perms"][perm] = True

            user[name]["permission"] = set_permission(user[name]["perms"])

            PYLOAD.setUserPermission(name, user[name]["permission"], user[name]["role"])

    return render_to_response(
        "admin.html", {"users": user, "permlist": perms}, [pre_processor]
    )


@route(r"/setup")
def setup():
    return base([_("Run pyLoad -s to access the setup.")])


@route(r"/info")
@login_required("STATUS")
def info():
    conf = PYLOAD.getConfigDict()
    extra = os.uname() if hasattr(os, "uname") else tuple()
    
    data = {
        "python": sys.version,
        "os": " ".join((os.name, sys.platform) + extra),
        "version": PYLOAD.getServerVersion(),
        "folder": os.path.abspath(PYLOAD_DIR),
        "config": os.path.abspath(""),
        "download": os.path.abspath(conf["general"]["download_folder"]["value"]),
        "freespace": formatSize(PYLOAD.freeSpace()),
        "remote": conf["remote"]["port"]["value"],
        "webif": conf["webui"]["port"]["value"],
        "language": conf["general"]["language"]["value"],
    }

    return render_to_response("info.html", data, [pre_processor])
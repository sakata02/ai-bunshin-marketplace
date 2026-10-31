"""NG の見張り（ng_guard.py）のテスト。止めるべきもの（bad）と、止めてはいけない日常の作業（good）。
正規表現を変えたら必ず実行する：python3 tests/test_ng_guard.py（失敗があれば終了コード1）"""
import json,subprocess,sys,os,tempfile
G=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","scripts","ng_guard.py")
# 見張りは本人のフォルダを ~/.ai-bunshin/owners.json に記録する。本物のホームに作らないよう、HOME を一時フォルダに差し替える
TEST_HOME=tempfile.mkdtemp(prefix="nghomeall_"); os.environ["HOME"]=TEST_HOME
R=tempfile.mkdtemp(prefix="ngtest_")
# R は「本人のフォルダ」：印（設定/config.json・00_タスク管理/data/tasks.json のどれか）がある（見張りはここでだけ動く）
os.makedirs(os.path.join(R,"設定")); os.makedirs(os.path.join(R,"00_タスク管理","data"))
open(os.path.join(R,"設定","config.json"),"w").write("{}"); open(os.path.join(R,"00_タスク管理","data","tasks.json"),"w").write("{}")
def run(tool,inp):
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp}),capture_output=True,text=True,cwd=R,env={**os.environ,"CLAUDE_PROJECT_DIR":R})
    return "STOP" if "deny" in p.stdout else "pass"
bad=[
"rm x","/bin/rm x","\\rm x","command rm x","env rm x","find 02_成果物 -type f -exec /bin/rm {} +","find . -exec rm {} \;","find . -name x -delete",
"perl -e 'unlink \"x\"'","python3 <<EOF\nimport shutil;shutil.rmtree('a')\nEOF","python3 -c \"import shutil;shutil.rmtree('a')\"","truncate -s 0 02_成果物/a.md",
"> 03_インプット/x","echo hi > 03_インプット/x","mv x ~/.Trash/","mv 02_成果物/a ~/.Trash/a","git checkout .","git checkout -- .","git restore .","git stash drop",
"/usr/bin/curl http://x","wget http://x","open mailto:a@b.c","open https://example.com","ruby -e 'File.delete(\"x\")'","node -e \"require('fs').rmSync('x')\"",
"bash -c 'rm x'","sh -c \"rm -rf x\"","echo x | xargs -I{} rm {}","xargs rm < list","/usr/bin/sudo ls","sudo ls","/bin/launchctl list","launchctl load x","kill -9 1","/bin/kill 1",
"cat x | sh","eval \"rm x\"","$(echo rm) x","r\\m x","dd if=/dev/null of=02_成果物/a.md","cp /dev/null 02_成果物/a.md",": > 02_成果物/a.md","tee 03_インプット/x < a","git push","gh pr create","/usr/bin/git push","git -C . push","git -c x=y push","git clean -fd","pip install x","python3 -m pip install x","brew install x","npm i x","osascript -e 'x'","/usr/bin/osascript x","ssh h","nc h 1","python3 -c 'import os;os.system(\"rm x\")'","python3 -c 'import os;os.system(\"curl x\")'","mv 02_成果物/a /dev/null","rm\tx","rm\\\nx","echo x >| 03_インプット/y","sed -i '' s/a/b/ 03_インプット/x","sed -i '' s/a/b/ ./CLAUDE.md","ln -sf /dev/null 02_成果物/a","cat a > .claude/settings.json","echo {} > .claude/settings.local.json","chmod 777 x","open -a Mail","shortcuts run x","mail -s hi a@b","swaks x","python3 -c \"import smtplib\"","zsh -c 'rm x'","bash -lc 'rm x'","sh -c 'ls; rm x'","git reset --hard","git branch -D x","git rebase -i","mkdir x && rm -r x","true || rm x","if true; then rm x; fi","{ rm x; }","for f in *; do rm $f; done","find . -delete","rsync -a a b","find . -name x -execdir rm {} +","find . -ok rm {} \;",
]
good=[
"grep -rn rm .","ls -la","cat 02_成果物/a.md","python3 /x/update_dashboard.py --plan-context","python3 /x/update_dashboard.py","mv 02_成果物/a 02_成果物/b","sed -i '' s/a/b/ 02_成果物/a.md","sed -i s/a/b/ 02_成果物/a.md","echo \"kill\"","echo rm","git status","git diff","git log --oneline","grep -n curl README.md","cat 04_ナレッジ/判断基準.md","head -5 x","python3 -c \"print(1)\"","python3 -m json.tool x","mkdir -p 02_成果物/総務","cp 02_成果物/a 02_成果物/b","ls 03_インプット/","cat 03_インプット/x.csv","python3 - <<EOF\nimport json;print(json.load(open('00_タスク管理/data/tasks.json')))\nEOF","wc -l x","date","echo 'please do not rm files' > 02_成果物/note.md","grep -rn 'git push' 04_ナレッジ","rg 'shutil.rmtree' .","python3 -c \"import openpyxl\"","command -v claude","uname","echo \"normal: 3+4\"","git add -A","git commit -m x","grep -n \"su\" x","ls | grep -i time","cat a | sort","python3 script.py --arg", "cd 02_成果物 && ls","echo $(date)","python3 -c \"from urllib.parse import quote\"","python3 -c \"import subprocess;print(1)\"","python3 -c \"import socket\"","echo 'import requests.post' > a.txt","python3 build.py  # fix rmdir","grep rm foo","cat x; rm_helper_notes","ls rm-notes","echo done;kill-switch","mv 02_成果物/a.xlsx 02_成果物/共通/","git restore-notes","git checkout main","git checkout -b x","git branch","sed -i '' s/a/b/ 02_成果物/CLAUDE.md.bak","echo hello > 02_成果物/a.md","python3 x.py > 02_成果物/out.txt","pip list","pip3 --version","npm ls","git push-notes","gh --version","wget-notes","time ls","nice ls","echo \"a; b\"","grep 'a|b' x","awk '{print $1}' x","ls ~/Library","open 02_成果物/a.xlsx","open -R 02_成果物/a.xlsx","touch 02_成果物/a",
]
fail=0
print("## BAD")
for c in bad:
    r=run("Bash",{"command":c})
    if r!="STOP": fail+=1; print("MISS",repr(c))
print("## GOOD")
for c in good:
    r=run("Bash",{"command":c})
    if r!="pass": fail+=1; print("FALSEPOS",repr(c))
print("## PATHS")
for t,p in [("Write",R+"/03_インプット/x.csv"),("Write",R+"/.claude/settings.json"),("Edit",R+"/.claude/settings.local.json"),("Write",R+"/.claude/rules/ai-bunshin-common.md"),("Write",R+"/02_成果物/a.md"),("Write",R+"/CLAUDE.md"),("Write",R+"/設定/config.json"),("Write",R+"/03_インプット/../.claude/settings.json"),("MultiEdit",R+"/03_インプット/a"),("NotebookEdit",R+"/03_インプット/a.ipynb"),("Write",R+"/.claude/hooks/x.sh"),("Write",R+"/.claude/settings.JSON")]:
    k="file_path" if t!="NotebookEdit" else "notebook_path"
    want="pass" if ("02_成果物" in p or p.endswith("CLAUDE.md")) else "STOP"  # 既にある config.json への内容なしの Write は、確かめられないので止める（T059）
    r=run(t,{k:p})
    if r!=want: fail+=1; print("PATH", r, "want", want, t, p.replace(R,"<R>"))
# 開発の置き場所（config の dev.projects と 05_開発/）の中だけ、その案件へのインストールを通す
EXT=tempfile.mkdtemp(prefix="ngrepo_")
os.makedirs(os.path.join(R,"設定"),exist_ok=True); os.makedirs(os.path.join(R,"05_開発","tool"),exist_ok=True)
json.dump({"dev":{"default_mode":"local","projects":[{"name":"ext","mode":"git","path":EXT}]}},open(os.path.join(R,"設定","config.json"),"w"))
dev_good=["cd 05_開発/tool && npm install","cd 05_開発/tool && npm ci","cd 05_開発/tool && .venv/bin/pip install pandas",
 "cd 05_開発/tool && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",f"cd {EXT} && npm install",f"npm --prefix {EXT} install",
 f"git -C {EXT} checkout -b ai/x",f"cd {EXT} && git add -A && git commit -m x","cd 05_開発/tool && git init"]
dev_bad=["npm install x","cd 05_開発/tool && npm install -g x","cd 05_開発/tool && python3 -m pip install x","cd 05_開発/tool && pip install x",
 "cd /tmp && npm install","cd 05_開発/tool && git push","cd 05_開発/tool && rm -rf node_modules","cd 05_開発/tool && npm install && cd ../.. && npm install x",
 f"cd {EXT} && git push origin main","cd 05_開発/tool && brew install x","cd 05_開発/tool && sudo npm install"]
dev_good+=["cd 05_開発/tool && source .venv/bin/activate && pip install pandas","(cd 05_開発/tool && npm install)",
 "cd 05_開発/tool && .venv/bin/python -m pip install x"]
dev_bad+=["cd 05_開発/tool && npm install --location=global foo","cd 05_開発/tool && npm install --prefix=/other","cd 05_開発/tool && gem install foo",
 "cd 05_開発/tool && .venv/bin/pip install --target /other x","cd 05_開発/tool && echo x/venv/bin/; pip install foo",
 "npm install; echo hi","(npm install)","cd 05_開発/tool && cd /tmp && npm install"]
# 今いる場所が開発の置き場所でも、cd の行き先が外ならインストールは止める
def run_cwd(cmd,cwd):
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":"Bash","tool_input":{"command":cmd},"cwd":cwd}),capture_output=True,text=True,cwd=R,env={**os.environ,"CLAUDE_PROJECT_DIR":R})
    return "STOP" if "deny" in p.stdout else "pass"
for c in ["cd /other && npm install","cd .. && cd .. && npm install"]:
    if run_cwd(c,EXT)!="STOP": fail+=1; print("DEV MISS (cwd)",repr(c))
if run_cwd("npm install",EXT)!="pass": fail+=1; print("DEV FALSEPOS (cwd)","npm install")
# プラグインのコピー（~/.claude/plugins/）は誰でも止める。プラグインの元は maintainer だけ通す
SRC=tempfile.mkdtemp(prefix="ngsrc_"); os.makedirs(os.path.join(SRC,"plugins","x",".claude-plugin"),exist_ok=True)
open(os.path.join(SRC,"plugins","x",".claude-plugin","plugin.json"),"w").write("{}")
CACHE=os.path.expanduser("~/.claude/plugins/cache/x/ai-bunshin/0.0.0/rules/r.md")
def cfg(maint):
    json.dump({"maintainer":maint,"dev":{"default_mode":"local","projects":[{"name":"ext","mode":"git","path":EXT}]}},open(os.path.join(R,"設定","config.json"),"w"))
cfg(False)
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":os.path.join(SRC,"plugins","x","rules","r.md")},"STOP"),
                      ("Bash",{"command":"echo x > ~/.claude/plugins/cache/x/r.md"},"STOP"),("Bash",{"command":"sed -i '' s/a/b/ ~/.claude/plugins/cache/x/r.md"},"STOP"),
                      ("Bash",{"command":"cat ~/.claude/plugins/cache/x/r.md"},"pass")]:
    if run(tool,inp)!=want: fail+=1; print("PLUGIN(non-maintainer)",want,tool,inp)
SRCF=os.path.join(SRC,"plugins","x","rules","r.md")
for c,want in [("python3 -c \"open('"+os.path.expanduser("~")+"/.claude/plugins/a','w').write('x')\"","STOP"),
               ("cd ~/.claude/plugins && cp x .","STOP"),("cp -t ~/.claude/plugins x","STOP"),("install x ~/.claude/plugins/a","STOP"),
               ("touch ~/.claude/plugins/a","STOP"),("mv ~/.claude/plugins/a b","STOP"),("cp x ../../.claude/plugins/a","STOP"),
               ("echo x > "+SRCF,"STOP"),("cp x "+SRCF,"STOP"),
               ("cat ~/.claude/plugins/a","pass"),("ls ~/.claude/plugins/","pass"),("diff ~/.claude/plugins/a b","pass"),
               ("cp ~/.claude/plugins/a ./b","pass"),("cat "+SRCF,"pass")]:
    if run("Bash",{"command":c})!=want: fail+=1; print("PLUGIN(bash, non-maintainer)",want,repr(c))
# 本人の許可する例外（ng_allow）でも、プラグインのコピーの保護は外れない
json.dump({"maintainer":False,"ng_allow":[".*"]},open(os.path.join(R,"設定","config.json"),"w"))
if run("Write",{"file_path":CACHE})!="STOP": fail+=1; print("PLUGIN ng_allow で外れた")
cfg(True)
for c,want in [("echo x > "+SRCF,"pass"),("touch ~/.claude/plugins/a","STOP")]:
    if run("Bash",{"command":c})!=want: fail+=1; print("PLUGIN(bash, maintainer)",want,repr(c))
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":os.path.join(SRC,"plugins","x","rules","r.md")},"pass")]:
    if run(tool,inp)!=want: fail+=1; print("PLUGIN(maintainer)",want,tool,inp)
cfg(False)
print("## DEV")
for c in dev_good:
    if run("Bash",{"command":c})!="pass": fail+=1; print("DEV FALSEPOS",repr(c))
for c in dev_bad:
    if run("Bash",{"command":c})!="STOP": fail+=1; print("DEV MISS",repr(c))
print("## 本人のフォルダの外・中")
def run_at(tool,inp,base,env_dir=True,payload_cwd=True):
    """base で動いている想定（CLAUDE_PROJECT_DIR・payload の cwd・プロセスの cwd をそこにそろえる）。"""
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}
    if env_dir: env["CLAUDE_PROJECT_DIR"]=base
    pl={"tool_name":tool,"tool_input":inp}
    if payload_cwd: pl["cwd"]=base
    p=subprocess.run(["python3",G],input=json.dumps(pl),capture_output=True,text=True,cwd=base,env=env)
    return "STOP" if "deny" in p.stdout else "pass"
OUT=tempfile.mkdtemp(prefix="ngout_")  # 設定なし＝ほかのプロジェクト
def mk_owner(marks):
    d=tempfile.mkdtemp(prefix="ngmark_")
    for m in marks:
        os.makedirs(os.path.dirname(os.path.join(d,m)),exist_ok=True); open(os.path.join(d,m),"w").write("{}")
    return d
M_CFG="設定/config.json"; M_TASK="00_タスク管理/data/tasks.json"; M_RULE=".claude/rules/ai-bunshin-common.md"
for c in ["rm x","git push","npm install x","curl https://example.com","sudo ls","git clean -fd","pip install x","ssh h","gh pr create","> 03_インプット/x","git reset --hard"]:
    if run_at("Bash",{"command":c},OUT)!="pass": fail+=1; print("OUTSIDE FALSEPOS",repr(c),OUT)
    # 印がどれか1つでもあれば本人のフォルダ（片方を動かして見張りを外す抜け道を塞ぐ）。config だけ・tasks.json だけ・共通ルールの写しだけ
    for marks in ([M_CFG],[M_TASK],[M_RULE]):
        d=mk_owner(marks)
        if run_at("Bash",{"command":c},d)!="STOP": fail+=1; print("HALF MISS",repr(c),marks)
for t,p in [("Write",OUT+"/03_インプット/x.csv"),("Write",OUT+"/.claude/settings.json"),("Edit",os.path.join(SRC,"plugins","x","rules","r.md"))]:
    if run_at(t,{"file_path":p},OUT)!="pass": fail+=1; print("OUTSIDE PATH FALSEPOS",t,p)
# 本人のフォルダの外でも、プラグインのコピー（~/.claude/plugins/）への書き込みは止める（読むだけは通す）
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":CACHE},"STOP"),
                      ("Bash",{"command":"echo x > ~/.claude/plugins/cache/x/r.md"},"STOP"),("Bash",{"command":"touch ~/.claude/plugins/a"},"STOP"),
                      ("Bash",{"command":"sed -i '' s/a/b/ ~/.claude/plugins/cache/x/r.md"},"STOP"),
                      ("Bash",{"command":"cat ~/.claude/plugins/cache/x/r.md"},"pass"),("Bash",{"command":"ls ~/.claude/plugins/"},"pass")]:
    if run_at(tool,inp,OUT)!=want: fail+=1; print("OUTSIDE PLUGIN COPY",want,tool,inp)
# 本人のフォルダの中、その下（05_開発/x）、環境変数なし・cwd だけの場合は、今までどおり止める
os.makedirs(os.path.join(R,"05_開発","x"),exist_ok=True)
SUB=os.path.join(R,"05_開発","x")
for base,kw in [(R,{}),(SUB,{}),(SUB,{"env_dir":False}),(R,{"env_dir":False,"payload_cwd":False})]:
    for c in ["rm x","git push","curl https://example.com","sudo ls"]:
        if run_at("Bash",{"command":c},base,**kw)!="STOP": fail+=1; print("INSIDE MISS",repr(c),base.replace(R,"<R>"),kw)
    if run_at("Write",{"file_path":R+"/03_インプット/x.csv"},base,**kw)!="STOP": fail+=1; print("INSIDE PATH MISS",base.replace(R,"<R>"),kw)
    if run_at("Bash",{"command":"ls -la"},base,**kw)!="pass": fail+=1; print("INSIDE FALSEPOS ls",base.replace(R,"<R>"),kw)
# 下のフォルダで動いていても、相対パスの基準は見つかった本人のフォルダ
if run_at("Write",{"file_path":os.path.join(SUB,"..","..","03_インプット","a")},SUB)!="STOP": fail+=1; print("INSIDE PATH (sub, ..)")
if run_at("Bash",{"command":"cd 05_開発/x && npm install"},R)!="pass": fail+=1; print("INSIDE DEV FALSEPOS (npm install in 05_開発/x)")
if run_at("Bash",{"command":"npm install"},SUB)!="pass": fail+=1; print("INSIDE DEV FALSEPOS (cwd=05_開発/x)")
# 印・設定・タスクの正本を動かす・名前を変える操作は止める（動かすと見張りが外れるため）
print("## 印の移動")
for c in ["mv 設定 設定_old","mv 設定/config.json 設定/c.json","git mv 設定/config.json 設定/c.json","mv 00_タスク管理/data/tasks.json 00_タスク管理/data/tasks.bak",
          "mv 00_タスク管理 x","mv 00_タスク管理/data x","mv x 設定/config.json","mv ./設定 /tmp/x","mv \"設定\" /tmp/x","cd 05_開発 && mv ../設定 x",
          "mv .claude/rules/ai-bunshin-common.md x","rename s/a/b/ 設定/config.json",
          "python3 -c \"import os;os.rename('設定','x')\"","python3 -c \"import shutil;shutil.move('00_タスク管理/data/tasks.json','x')\"",
          "python3 -c \"from pathlib import Path;Path('設定').rename('x')\"","python3 -c \"import os;os.replace('設定/config.json','x')\"",
          "mv . /tmp/moved","mv "+R+" /tmp/moved","mv "+os.path.dirname(R)+" /tmp/moved2","mv -t /tmp "+R]:
    if run_at("Bash",{"command":c},R)!="STOP": fail+=1; print("MOVE MISS",repr(c))
for c in ["mv 02_成果物/a 02_成果物/b","mv 02_成果物/a.md .","mv 02_成果物/a.md ..","ls 設定","cat 設定/config.json","cp 設定/config.json 02_成果物/config.bak","mv 02_成果物/設定_old.md 02_成果物/x.md",
          "python3 -c \"print('設定'.replace('a','b'))\"","python3 -c \"print(open('設定/config.json').read())\"","git mv 02_成果物/a 02_成果物/b","mv 05_開発/x 05_開発/y"]:
    if run_at("Bash",{"command":c},R)!="pass": fail+=1; print("MOVE FALSEPOS",repr(c))
# リンクを解かない道でも本人のフォルダを見つける（本人のフォルダの下のリンクが外を指していても止める）
print("## リンク")
LNKTARGET=tempfile.mkdtemp(prefix="nglink_"); LNK=os.path.join(R,"05_開発","ext")
if not os.path.lexists(LNK): os.symlink(LNKTARGET,LNK)
for c in ["git push","rm x","curl https://example.com"]:
    for kw in ({},{"env_dir":False}):
        if run_at("Bash",{"command":c},LNK,**kw)!="STOP": fail+=1; print("SYMLINK MISS",repr(c),kw)
# 外で始めたセッションでも、操作の中のパスが本人のフォルダを指すなら、その本人のフォルダを基準に判定する
print("## 外からのパス")
HOMED=tempfile.mkdtemp(prefix="nghome_"); OWN=os.path.join(HOMED,"own"); os.makedirs(os.path.join(HOMED,"sub"))
for m in (M_CFG,M_TASK): os.makedirs(os.path.dirname(os.path.join(OWN,m)),exist_ok=True); open(os.path.join(OWN,m),"w").write("{}")
def run_home(tool,inp,base):
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["HOME"]=HOMED
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp,"cwd":base}),capture_output=True,text=True,cwd=base,env=env)
    return "STOP" if "deny" in p.stdout else "pass"
for tool,inp,want in [
    ("Bash",{"command":"cd /tmp && rm -rf "+OWN+"/03_インプット"},"STOP"),("Bash",{"command":"cd "+HOMED+" && rm -rf "+OWN+"/03_インプット"},"STOP"),
    ("Bash",{"command":"rm -rf ~/own/03_インプット"},"STOP"),("Bash",{"command":"rm -rf $HOME/own/03_インプット"},"STOP"),
    ("Bash",{"command":"rm -rf \"$HOME/own/03_インプット\""},"STOP"),("Bash",{"command":"rm -rf ${HOME}/own"},"STOP"),
    ("Bash",{"command":"git -C ~/own push"},"STOP"),("Bash",{"command":"echo x > "+OWN+"/03_インプット/a"},"STOP"),
    ("Bash",{"command":"mv "+OWN+"/設定 /tmp/x"},"STOP"),("Bash",{"command":"mv ~/own/00_タスク管理/data/tasks.json /tmp/x"},"STOP"),
    ("Write",{"file_path":OWN+"/03_インプット/a.csv"},"STOP"),("Write",{"file_path":OWN+"/.claude/settings.json"},"STOP"),
    ("Edit",{"file_path":OWN+"/.claude/hooks/x.sh"},"STOP"),("MultiEdit",{"file_path":OWN+"/03_インプット/a"},"STOP"),
    ("NotebookEdit",{"notebook_path":OWN+"/03_インプット/a.ipynb"},"STOP"),
    ("Write",{"file_path":"../own/03_インプット/a"},"STOP"),
    ("Bash",{"command":"rm -rf build"},"pass"),("Bash",{"command":"git push"},"pass"),("Bash",{"command":"curl https://example.com"},"pass"),
    ("Bash",{"command":"rm -rf /tmp/build ~/other/x"},"pass"),("Bash",{"command":"cat ~/own/設定/config.json"},"pass"),
    ("Bash",{"command":"ls ~/own/03_インプット"},"pass"),("Bash",{"command":"echo x > ~/own/02_成果物/a.md"},"pass"),
    ("Write",{"file_path":OWN+"/02_成果物/a.md"},"pass"),("Write",{"file_path":"/tmp/x.md"},"pass"),("Write",{"file_path":HOMED+"/other/03_インプット/a"},"pass")]:
    if run_home(tool,inp,os.path.join(HOMED,"sub") if inp.get("file_path","").startswith("..") else "/tmp")!=want: fail+=1; print("FROM-OUTSIDE",want,tool,inp)
# 見張りの入力が壊れていたら：本人のフォルダの中なら止める、外なら通す（例外で落ちて通る側にならない）
print("## 壊れた入力")
def run_raw(text,base):
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["CLAUDE_PROJECT_DIR"]=base
    p=subprocess.run(["python3",G],input=text,capture_output=True,text=True,cwd=base,env=env)
    return ("STOP" if "deny" in p.stdout else "pass"), p.returncode
for text in ["[]","null","123","\"str\"","{broken","","{\"tool_name\":\"Bash\",\"tool_input\":\"rm x\",\"cwd\":5}","{\"tool_name\":\"Write\",\"tool_input\":[1]}"]:
    for base,want in ((R,"STOP"),(SUB,"STOP"),(OUT,"pass")):
        got,rc=run_raw(text,base)
        if got!=want or rc!=0: fail+=1; print("BROKEN INPUT",repr(text),base.replace(R,"<R>"),got,rc,"want",want)
# ---- 本人のフォルダの記録（~/.ai-bunshin/owners.json）と、印・本人のフォルダを動かして見張りを外す抜け道（T058 probe2・probe3）----
print("## 記録と抜け道")
import unicodedata,getpass
PH=tempfile.mkdtemp(prefix="ngph_")  # この節のホーム
W=os.path.join(PH,"workspace"); P=os.path.join(W,"AI坂田"); OUTP=os.path.join(W,"other")
for d in ["設定","00_タスク管理/data","05_開発/x","02_成果物/共通","03_インプット","02_成果物/設定"]: os.makedirs(os.path.join(P,d))
open(P+"/設定/config.json","w").write("{}"); open(P+"/00_タスク管理/data/tasks.json","w").write("{}"); os.makedirs(OUTP)
os.makedirs(P+"/.claude/rules"); open(P+"/.claude/rules/ai-bunshin-common.md","w").write("x")  # .clau* が実際に当たるように
RM="r"+"m"
def run_p(tool,inp,where,home=PH):
    """where：'in'＝本人のフォルダ P で動く、'out'＝外（OUTP）、それ以外はそのフォルダで動く（CLAUDE_PROJECT_DIR もそこ）。"""
    base={"in":P,"out":OUTP}.get(where,where)
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["HOME"]=home; env["CLAUDE_PROJECT_DIR"]=base
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp,"cwd":base}),capture_output=True,text=True,cwd=base,env=env)
    return "STOP" if "deny" in p.stdout else "pass"
# 本人のフォルダで1回動くと、記録に足される（本物のホームではなく PH の下）
run_p("Bash",{"command":"ls"},"in")
REC=os.path.join(PH,".ai-bunshin","owners.json")
try: recs=json.load(open(REC))["owners"]
except Exception: recs=[]
if not any(os.path.realpath(x)==os.path.realpath(P) for x in recs): fail+=1; print("RECORD 記録されていない",recs)
NFD=unicodedata.normalize("NFD","03_インプット")
def Bc(c): return ("Bash",{"command":c})
probe=[  # (名前, (tool, inp), where, 期待)
 # probe2：通ってしまっていたもの
 ("in: cp -r 設定 && rm -r 設定",Bc(f"cp -r 設定 /tmp/x && {RM} -r 設定"),"in","STOP"),
 ("in: find 設定 -delete",Bc("find 設定 -delete"),"in","STOP"),
 ("in: rsync --remove-source-files",Bc("rsync -a --remove-source-files 設定/ /tmp/x/"),"in","STOP"),
 ("in: shutil.rmtree('設定')",Bc("python3 -c \"import shutil;shutil.rmtree('設定')\""),"in","STOP"),
 ("in: mv 設? (glob)",Bc("mv 設? 設定_old"),"in","STOP"),
 ("in: mv 00_タ* (glob)",Bc("mv 00_タ* /tmp/x"),"in","STOP"),
 ("in: mv .clau* (glob)",Bc("mv .clau* /tmp/y"),"in","STOP"),
 ("in: cd 設定 && mv config.json",Bc("cd 設定 && mv config.json c.json"),"in","STOP"),
 ("in: cd data && mv tasks.json",Bc("cd 00_タスク管理/data && mv tasks.json x"),"in","STOP"),
 ("in: git rm -r 設定 tasks.json",Bc(f"git {RM} -rq 設定 00_タスク管理/data/tasks.json"),"in","STOP"),
 ("in: zip -rm",Bc("zip -rmq /tmp/a.zip 設定"),"in","STOP"),
 ("in: os.rename(getcwd)",Bc("python3 -c \"import os;os.rename(os.getcwd(),'/tmp/x')\""),"in","STOP"),
 ("in: shutil.move(abs root)",Bc(f"python3 -c \"import shutil;shutil.move('{P}','/tmp/x')\""),"in","STOP"),
 ("in: mv ../AI坂田",Bc("mv ../AI坂田 /tmp/x"),"in","STOP"),
 ("in: cd .. && mv AI坂田",Bc("cd .. && mv AI坂田 AI坂田_old"),"in","STOP"),
 ("in: mv \"$PWD\"",Bc("mv \"$PWD\" /tmp/x"),"in","STOP"),
 ("in: mv $(pwd)",Bc("mv $(pwd) /tmp/x"),"in","STOP"),
 ("in: mv 親",Bc(f"mv {W} /tmp/x"),"in","STOP"),
 ("in: cp x ABS/03_インプット",Bc(f"cp x {P}/03_インプット/a.csv"),"in","STOP"),
 ("in: echo > \"03_インプット\"/a",Bc("echo x > \"03_インプット\"/a.csv"),"in","STOP"),
 ("in: echo > ABS/03_インプット",Bc(f"echo x > {P}/03_インプット/a.csv"),"in","STOP"),
 ("in: Write NFD 03_インプット",("Write",{"file_path":P+"/"+NFD+"/a.csv"}),"in","STOP"),
 # （in: Write 設定/config.json の ng_allow の書き換えは T059 で扱う）
 ("out: rm -rf ABS/03_インプット",Bc(f"{RM} -rf {P}/03_インプット"),"out","STOP"),
 ("out: rm -rf ../AI坂田/03_インプット",Bc(f"{RM} -rf ../AI坂田/03_インプット"),"out","STOP"),
 ("out: cd ../AI坂田 && rm",Bc(f"cd ../AI坂田 && {RM} -rf 03_インプット"),"out","STOP"),
 ("out: cd ABS && rm",Bc(f"cd {P} && {RM} -rf 03_インプット"),"out","STOP"),
 ("out: cd W && rm AI坂田/03_インプット",Bc(f"cd {W} && {RM} -rf AI坂田/03_インプット"),"out","STOP"),
 ("out: rm \"QUOTED\"/03_インプット",Bc(f"{RM} -rf \"{P}\"/03_インプット"),"out","STOP"),
 ("out: git -C<abs> clean",Bc(f"git -C{P} clean -fdx"),"out","STOP"),
 ("out: 61個のパスのあと",Bc(f"{RM} -rf "+" ".join(f"/nx{i}" for i in range(61))+f" {P}/03_インプット"),"out","STOP"),
 ("out: Write ../AI坂田/03_インプット",("Write",{"file_path":"../AI坂田/03_インプット/a.csv"}),"out","STOP"),
 ("out: mv ABS/設定",Bc(f"mv {P}/設定 /tmp/x"),"out","STOP"),
 # probe2：誤検知だったもの
 ("FP in: git mv 02_成果物",Bc("git mv 02_成果物/a.md 02_成果物/b.md"),"in","pass"),
 ("FP in: mv 02_成果物/x 共通/",Bc("mv 02_成果物/x 02_成果物/共通/"),"in","pass"),
 ("FP in: mv a.md 02_成果物/設定/",Bc("mv a.md 02_成果物/設定/"),"in","pass"),
 ("FP in: mv 02_成果物/設定",Bc("mv 02_成果物/設定 02_成果物/old"),"in","pass"),
 ("FP in: mv a.xlsx 00_タスク管理/",Bc("mv a.xlsx 00_タスク管理/"),"in","pass"),
 ("FP in: mv 00_タスク管理/a.xlsx data/",Bc("mv 00_タスク管理/a.xlsx 00_タスク管理/data/"),"in","pass"),
 ("FP in: str.replace + '設定'",Bc("python3 -c \"s='設定';print(s.replace('a','b'))\""),"in","pass"),
 ("FP in: tasks.json + .replace(x)",Bc("python3 -c \"import json;d=json.load(open('00_タスク管理/data/tasks.json'));print(str(d).replace(x))\""),"in","pass"),
 ("FP in: 読むだけ",Bc("ls 設定 && cat 00_タスク管理/data/tasks.json | grep T0 && git status && git log -3 && git diff"),"in","pass"),
 ("FP out: mv a b",Bc("mv a b"),"out","pass"),
 ("FP out: rm -rf build",Bc(f"{RM} -rf build"),"out","pass"),
 ("FP out: git push",Bc("git push origin main"),"out","pass"),
 ("FP out: npm install",Bc("npm install"),"out","pass"),
 ("FP out: mv build/設定 dist/",Bc("mv build/設定 dist/"),"out","pass"),
 ("FP out: cat 本人のファイル && rm -rf build",Bc(f"cat {P}/CLAUDE.md && {RM} -rf build"),"out","pass"),
 # probe3（~ は PH）
 ("p3 out: rm ~/workspace/AI坂田",Bc(f"{RM} -rf ~/workspace/AI坂田/03_インプット"),"/tmp","STOP"),
 ("p3 out: rm \"$HOME\"/workspace",Bc(f"{RM} -rf \"$HOME\"/workspace/AI坂田/03_インプット"),"/tmp","STOP"),
 ("p3 out: rm \"${HOME}/workspace",Bc(f"{RM} -rf \"${{HOME}}/workspace/AI坂田/03_インプット\""),"/tmp","STOP"),
 ("p3 out: cd ~/workspace/AI坂田 && rm",Bc(f"cd ~/workspace/AI坂田 && {RM} -rf 03_インプット"),"/tmp","STOP"),
 ("p3 out: cd ~/workspace && rm AI坂田/",Bc(f"cd ~/workspace && {RM} -rf AI坂田/03_インプット"),"/tmp","STOP"),
 # 「p3 out: rm ~user/（名前で拾う）」は外した（T058）：R1 で名前の部分一致をやめた。~user は本物のホームに広がり、本物の本人のフォルダの ng_log に書いてしまうため。~user の広げ方は下の EXPAND で確かめる
 ("p3 out: find ABS -delete",Bc(f"find {P}/03_インプット -delete"),"/tmp","STOP"),
 ("p3 out: mv \"$HOME/workspace/AI坂田\"",Bc("mv \"$HOME/workspace/AI坂田\" /tmp/x"),"/tmp","STOP"),
 ("p3 in: mv 設? 00_タ* .clau*",Bc("mv 設? 00_タ* .clau* /tmp/x"),"in","STOP"),
 ("p3 in: mv \"$HOME/workspace/AI坂田\"",Bc("mv \"$HOME/workspace/AI坂田\" /tmp/x"),"in","STOP"),
 ("p3 FP in: os.replace(tmp, tasks.json)",Bc("python3 -c \"import json,os;d=json.load(open('00_タスク管理/data/tasks.json'));json.dump(d,open('t.tmp','w'));os.replace('t.tmp','00_タスク管理/data/tasks.json')\""),"in","pass"),
 ("p3 FP in: pandas rename(columns=)",Bc("python3 -c \"import pandas as pd;df=pd.DataFrame(json.load(open('00_タスク管理/data/tasks.json'))['tasks']).rename(columns={'id':'ID'})\""),"in","pass"),
 ("p3 out: Write ABS/03_インプット",("Write",{"file_path":P+"/03_インプット/a.csv","content":"x"}),"/tmp","STOP"),
 # 本人のフォルダそのもの・親を、別の書き方で動かす・消す
 ("out: cd W && mv AI坂田",Bc("cd .. && mv AI坂田 x"),"out","STOP"),
 ("out: bash -c 'mv ../AI坂田'",Bc("bash -c 'mv ../AI坂田 /tmp/x'"),"out","STOP"),
 ("out: bash -c 'cd .. && rm AI*/03'",Bc(f"bash -c 'cd .. && {RM} -rf AI*/03_インプット'"),"out","STOP"),
 ("out: cd .. && rm AI*/03 (glob)",Bc(f"cd .. && {RM} -rf AI*/03_インプット"),"out","STOP"),
 ("out: mv W/AI坂? (glob)",Bc(f"mv {W}/AI坂? /tmp/x"),"out","STOP"),
 ("out: zip -rm 本人のフォルダ",Bc("zip -rmq /tmp/a.zip ~/workspace/AI坂田"),"out","STOP"),
 ("out: find 親 -delete",Bc("find ~/workspace -name '*.json' -delete"),"out","STOP"),
 ("out: git -C 親 rm -r",Bc(f"git -C ~/workspace {RM} -r AI坂田"),"out","STOP"),
 ("out: Path(親).rename",Bc(f"python3 -c \"from pathlib import Path;p=Path('{W}');p.rename('/tmp/w')\""),"out","STOP"),
 ("out: for で受け渡す",Bc(f"for d in ~/workspace/AI坂田; do {RM} -rf $d/03_インプット; done"),"out","STOP"),
 ("out: 変数で受け渡す",Bc(f"D=~/workspace/AI坂田; {RM} -rf $D/03_インプット"),"out","STOP"),
 ("out: パイプで受け渡す",Bc(f"echo {P}/03_インプット | xargs {RM} -rf"),"out","STOP"),
 ("in: mv x 設定/config.json（上書き）",Bc("mv x 設定/config.json"),"in","STOP"),
 ("in: git rm --cached",Bc(f"git {RM} --cached 02_成果物/a.md"),"in","STOP"),
 ("in: Bash NFD 03_インプット",Bc("echo x > "+NFD+"/a.csv"),"in","STOP"),
 ("in: cp x \"ABS\"/03_インプット",Bc(f"cp x \"{P}\"/03_インプット/a.csv"),"in","STOP"),
 ("FP out: cd ~ && git push",Bc("cd ~ && git push"),"out","pass"),
 ("FP out: ls 本人のフォルダ && npm install",Bc("ls ~/workspace/AI坂田 && npm install"),"out","pass"),
 ("FP out: rm -rf ./dist（外の案件）",Bc(f"{RM} -rf ./dist node_modules"),"out","pass"),
 ("FP in: mv 02_成果物/a.md .",Bc("mv 02_成果物/a.md ."),"in","pass"),
 ("FP in: cp 設定/config.json 02_成果物/",Bc("cp 設定/config.json 02_成果物/c.bak"),"in","pass"),
]
for name,(tool,inp),where,want in probe:
    got=run_p(tool,inp,where)
    if got!=want: fail+=1; print("PROBE",got,"want",want,name)
# ~user は、その人の本当のホーム（pw_dir）に広げる（見張りを動かさずに、関数だけ確かめる。本物のフォルダには触れない）
import importlib.util,pwd
_sp=importlib.util.spec_from_file_location("ng_guard_mod",G); NGM=importlib.util.module_from_spec(_sp); _sp.loader.exec_module(NGM)
if NGM.expand("~"+getpass.getuser()+"/x","/")!=os.path.join(pwd.getpwnam(getpass.getuser()).pw_dir,"x"): fail+=1; print("EXPAND ~user")
# 印が無くなっても、記録にあるフォルダは本人のフォルダとして見張る（印を消す・動かす抜け道を塞ぐ）
NM=os.path.join(PH,"nomark"); os.makedirs(os.path.join(NM,"05_開発"))
json.dump({"owners":recs+[NM]},open(REC,"w"))
for tool,inp,where,want in [("Bash",{"command":f"{RM} x"},NM,"STOP"),("Bash",{"command":"git push"},os.path.join(NM,"05_開発"),"STOP"),
                            ("Bash",{"command":"ls"},NM,"pass"),("Write",{"file_path":NM+"/03_インプット/a"},"out","STOP"),
                            ("Bash",{"command":f"{RM} -rf {NM}/03_インプット"},"out","STOP"),("Bash",{"command":f"mv {NM} /tmp/x"},"out","STOP"),
                            ("Bash",{"command":f"{RM} -rf build"},"out","pass")]:
    if run_p(tool,inp,where)!=want: fail+=1; print("NO-MARK",want,tool,inp,where.replace(PH,"<PH>"))
# 見張りの記録（~/.ai-bunshin/）は、どこからでも書き換え・削除・移動を止める（読むだけは通す）
for where in ("in","out"):
    for tool,inp,want in [("Write",{"file_path":REC},"STOP"),("Edit",{"file_path":REC},"STOP"),
                          ("Bash",{"command":"echo '{}' > ~/.ai-bunshin/owners.json"},"STOP"),("Bash",{"command":f"{RM} ~/.ai-bunshin/owners.json"},"STOP"),
                          ("Bash",{"command":"mv ~/.ai-bunshin /tmp/x"},"STOP"),("Bash",{"command":f"{RM} -rf ~/.ai-*"},"STOP"),
                          ("Bash",{"command":"sed -i '' s/a/b/ ~/.ai-bunshin/owners.json"},"STOP"),("Bash",{"command":"cp /tmp/x $HOME/.ai-bunshin/owners.json"},"STOP"),
                          ("Bash",{"command":"python3 -c \"import os;os.remove(os.path.expanduser('~/.ai-bunshin/owners.json'))\""},"STOP"),
                          ("Bash",{"command":"cd ~ && mv .ai-bunshin x"},"STOP"),("Bash",{"command":f"cd ~/.ai-bunshin && {RM} owners.json"},"STOP"),
                          ("Bash",{"command":"cat ~/.ai-bunshin/owners.json"},"pass"),("Bash",{"command":"ls -la ~/.ai-bunshin 2>&1"},"pass")]:
        if run_p(tool,inp,where)!=want: fail+=1; print("RECORDS",where,want,tool,inp)
# 長いコマンド：外では指している本人のフォルダを探しきれないので、記録にあるすべてで判定する（止める側）。中の長い書き出しは通す
LONG=" ".join(["w"]*3100)
for c,where,want in [(f"echo {LONG}; {RM} -rf build","out","STOP"),(f"echo {LONG}","out","pass"),
                     ("cat > 02_成果物/long.md <<'EOF'\n"+"\n".join(["文章 mv find tar の説明"]*1200)+"\nEOF","in","pass")]:
    if run_p("Bash",{"command":c},where)!=want: fail+=1; print("LONG",where,want,c[:40])
# ng_allow（.*）でも、本人のフォルダそのもの・見張りの記録の保護は外れない
json.dump({"ng_allow":[".*"]},open(P+"/設定/config.json","w"))
for c in [f"mv {P} /tmp/x",f"{RM} ~/.ai-bunshin/owners.json"]:
    if run_p("Bash",{"command":c},"in")!="STOP": fail+=1; print("NO-EXCEPTION",c)
if run_p("Bash",{"command":f"{RM} x"},"in")!="pass": fail+=1; print("ng_allow が効かない（rm x）")
json.dump({},open(P+"/設定/config.json","w"))
# ---- T058 方式 v2：実体（st_dev・st_ino）で比べる・同じコマンドの中で作るリンク・R1〜R9・--explain ----
# 表の形：(ID, 動く場所, ツール, 入力, 期待 deny/pass, deny の理由に含む語)。R1〜R4 は通す側の行を先に書く
print("## T058 方式 v2")
VH=os.path.realpath(tempfile.mkdtemp(prefix="ngv2_"))  # この節のホーム（本物の ~ には触れない）
VW=VH+"/workspace"; VR=VW+"/AI坂田"; VO=VW+"/other/proj"; VK=VW+"/work"
for d in ["設定","00_タスク管理/data","05_開発/x","02_成果物/共通","02_成果物/設定","03_インプット",".claude/rules"]: os.makedirs(VR+"/"+d)
for f,t in [("設定/config.json","{}"),("00_タスク管理/data/tasks.json","{}"),(".claude/rules/ai-bunshin-common.md","x"),("CLAUDE.md","x"),("03_インプット/a.csv","a"),("02_成果物/a.md","x")]:
    open(VR+"/"+f,"w").write(t)
os.makedirs(VO+"/src"); os.makedirs(VH+"/.claude/plugins/cache/x/ai-bunshin/scripts")
for d in ["設定","03_インプット"]: os.makedirs(VK+"/"+d)  # 名前が一般的な語（work）の本人のフォルダ（R1）
open(VK+"/設定/config.json","w").write("{}")
os.symlink("../03_インプット",VR+"/02_成果物/lk")          # 本人のフォルダの中のリンク（R7）
os.symlink("共通",VR+"/02_成果物/lkok")                      # 保護していない所へのリンク（通す）
os.symlink(VR+"/03_インプット",VO+"/inp")                     # 外から本人の 03_インプット へのリンク（R7）
os.link(VR+"/03_インプット/a.csv",VR+"/02_成果物/hl.csv")    # ハードリンク（R5）
VNFD_T=unicodedata.normalize("NFD","00_タスク管理")
def run_v(tool,inp,where,home=None,timeit=False):
    """where：in＝本人のフォルダ、out＝外の案件、ws＝本人のフォルダの親（workspace）、それ以外はそのフォルダ。(判定, 理由) を返す。"""
    import time
    base={"in":VR,"out":VO,"ws":VW,"home":VH}.get(where,where)
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["HOME"]=home or VH; env["CLAUDE_PROJECT_DIR"]=base
    t0=time.time()
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp,"cwd":base}),capture_output=True,text=True,cwd=base,env=env)
    dt=time.time()-t0
    try: o=json.loads(p.stdout)["hookSpecificOutput"]; got=(o["permissionDecision"],o.get("permissionDecisionReason",""))
    except Exception: got=("pass","")
    if p.returncode!=0: got=("rc%d"%p.returncode,p.stderr[-200:])
    return (got,dt) if timeit else got
run_v("Bash",{"command":"ls"},"in"); run_v("Bash",{"command":"ls"},VK)  # 記録に足す
def Bv(c): return ("Bash",{"command":c})
V=[
 # R1：外のセッションで、本人のフォルダの名前が語に含まれるだけでは本人の規則を当てない（通す側を先に）
 ("R1-p1","out",*Bv("git commit -m 'AI坂田 の件' && npm install"),"pass",""),
 ("R1-p2","out",*Bv("git commit -m 'AI坂田 の件' && git push origin main"),"pass",""),
 ("R1-p3","out",*Bv("git commit -m 'work in progress' && git push"),"pass",""),
 ("R1-p4","out",*Bv(f"{RM} -rf {VO}/build"),"pass",""),
 ("R1-p5","out",*Bv("echo AI坂田 && npm install && "+RM+" -rf dist"),"pass",""),
 # R2：find の -exec は、直後が rm・mv などのときだけ「動かす・消す」（通す側を先に）
 ("R2-p1","in",*Bv("find . -name '*.md' -exec grep -l TODO {} +"),"pass",""),
 ("R2-p2","ws",*Bv("find . -name '*.md' -exec grep -l TODO {} +"),"pass",""),
 ("R2-p3","in",*Bv("find 設定 -name '*.json' -exec cat {} \\;"),"pass",""),
 ("R2-p4","in",*Bv("find 00_タスク管理 -type f -execdir wc -l {} +"),"pass",""),
 # R3：03_インプット から読み出すのは通す（通す側を先に）
 ("R3-p1","in",*Bv("cp 03_インプット/a.csv 02_成果物/a.csv"),"pass",""),
 ("R3-p2","in",*Bv("cp 03_インプット/a.csv 02_成果物/"),"pass",""),
 ("R3-p3","in",*Bv("cp -r 03_インプット 02_成果物/bk"),"pass",""),
 ("R3-p4","in",*Bv("ls 03_インプット && head 03_インプット/a.csv"),"pass",""),
 ("R3-p5","in",*Bv("python3 -c \"print(open('03_インプット/a.csv').read())\""),"pass",""),
 ("R3-p6","in",*Bv("diff 03_インプット/a.csv 02_成果物/a.md"),"pass",""),
 # R4：2>/dev/null・2>&1・>/dev/null は書き込みと見ない（通す側を先に）
 ("R4-p1","in",*Bv(f"ls {VH}/.claude/plugins 2>/dev/null | head"),"pass",""),
 ("R4-p2","in",*Bv(f"python3 {VH}/.claude/plugins/cache/x/ai-bunshin/scripts/update_dashboard.py --status 2>&1 | tail"),"pass",""),
 ("R4-p3","in",*Bv("cat ~/.claude/plugins/x >/dev/null 2>&1"),"pass",""),
 ("R4-p4","in",*Bv("mv 02_成果物/a.md 02_成果物/b.md > /dev/null"),"pass",""),
 ("R4-p5","out",*Bv("ls -la ~/.ai-bunshin 2>/dev/null"),"pass",""),
 ("R4-p6","in",*Bv("git status 2>&1 | head &>/dev/null"),"pass",""),
]
V+=[
 # R1：止める側（パスとして解いたものが、記録の実体と同じかその下のときだけ当てる）
 ("R1-s1","out",*Bv(f"cd ~/workspace && {RM} -rf AI坂田/03_インプット"),"deny","削除"),
 ("R1-s2","ws",*Bv(f"{RM} -rf \"AI坂田/03_インプット\""),"deny","削除"),
 ("R1-s3","out",*Bv(f"{RM} -rf ../../AI坂田/03_インプット"),"deny","削除"),
 ("R1-s4","out",*Bv(f"{RM} -rf ~/workspace/work/03_インプット"),"deny","削除"),
 ("R1-s5","out",*Bv(f"git commit -m 'AI坂田 の件' && {RM} -rf {VR}/03_インプット"),"deny","削除"),
 # R2：止める側
 ("R2-s1","in",*Bv(f"find 設定 -exec {RM} {{}} +"),"deny","削除"),
 ("R2-s2","ws",*Bv(f"find . -name node_modules -prune -exec {RM} -rf {{}} +"),"deny","本人のフォルダそのもの"),  # 起点の workspace が本人のフォルダを含む
 ("R2-s3","in",*Bv("find 設定 -exec mv {} /tmp/x \\;"),"deny","正本の移動"),
 ("R2-s4","in",*Bv("find 設定 -delete"),"deny","削除"),
 ("R2-s5","ws",*Bv("find . -name '*.json' -execdir /bin/mv {} /tmp/ \\;"),"deny","本人のフォルダそのもの"),
 # R3：止める側（書き込み先と mv の元が 03_インプット の実体の下か）
 ("R3-s1","in",*Bv("mv 03_インプット /tmp/x"),"deny","元データ"),
 ("R3-s2","in",*Bv("cp a.csv 03_インプット"),"deny","元データ"),
 ("R3-s3","in",*Bv("mv a.csv 03_インプット"),"deny","元データ"),
 ("R3-s4","in",*Bv("unzip -o x.zip -d 03_インプット"),"deny","元データ"),
 ("R3-s5","in",*Bv("python3 -c \"open('03_インプット/a.csv','w').write('x')\""),"deny","元データ"),
 ("R3-s6","in",*Bv("cd 03_インプット && touch b.csv"),"deny","元データ"),
 ("R3-s7","in",*Bv("tee 03_インプット/b.csv < a"),"deny","元データ"),
 ("R3-s8","in",*Bv("mv 03_インプット/a.csv 02_成果物/"),"deny","元データ"),
 ("R3-s9","in",*Bv("echo x >> 03_インプット/a.csv"),"deny","元データ"),
 ("R3-s10","in",*Bv("cp -t 03_インプット a.csv"),"deny","元データ"),
 ("R3-s11","in",*Bv("cd 03_インプット && tar -xf ../x.tar"),"deny","元データ"),
 # R4：止める側（/dev/null を除いても書き込みが残るもの）
 ("R4-s1","in",*Bv("echo x > ~/.claude/plugins/a 2>/dev/null"),"deny","プラグインのコピー"),
 ("R4-s2","in",*Bv("ls ~/.claude/plugins 2>/dev/null && touch ~/.claude/plugins/a"),"deny","プラグインのコピー"),
 ("R4-s3","in",*Bv("echo x 2>&1 > 03_インプット/a.csv"),"deny","元データ"),
 ("R4-s4","out",*Bv("ls ~/.ai-bunshin 2>/dev/null; echo '{}' > ~/.ai-bunshin/owners.json"),"deny","見張りの記録"),
 # R5：表記違い（大文字小文字・NFD・//・/./・ハードリンク）を実体で解く
 ("R5-1","in",*Bv("mv ../ai坂田 /tmp/x"),"deny","本人のフォルダそのもの"),
 ("R5-2","in",*Bv("mv 設定/CONFIG.JSON /tmp/x"),"deny","正本の移動"),
 ("R5-3","in",*Bv("mv .CLAUDE /tmp/x"),"deny","正本の移動"),
 ("R5-4","out",*Bv(f"mv {VW}/ai坂田 /tmp/x"),"deny","本人のフォルダそのもの"),
 ("R5-5","in",*Bv(f"mv {VNFD_T}/data /tmp/x"),"deny","正本の移動"),
 ("R5-6","in",*Bv("mv 設定//config.json /tmp/x"),"deny","正本の移動"),
 ("R5-7","in",*Bv("mv 設定/./config.json /tmp/x"),"deny","正本の移動"),
 ("R5-8","in","Write",{"file_path":VR+"/.CLAUDE/settings.json"},"deny","権限・設定"),
 ("R5-9","in","Write",{"file_path":VR+"/02_成果物/hl.csv"},"deny","元データ"),
 ("R5-10","in",*Bv("echo x > 02_成果物/hl.csv"),"deny","元データ"),
 ("R5-11","in",*Bv("mv x 設定/CONFIG.JSON"),"deny","上書き"),
 ("R5-12","out","Write",{"file_path":VH+"/.AI-BUNSHIN/owners.json"},"deny","見張りの記録"),
 ("R5-13","out",*Bv("mv ~/WORKSPACE/AI坂田/設定 /tmp/x"),"deny","正本の移動"),
 ("R5-14","in","Write",{"file_path":VR+"/設定/../03_インプット//b.csv"},"deny","元データ"),
 ("R5-p1","in",*Bv("cat 設定/CONFIG.JSON 02_成果物/hl.csv"),"pass",""),
 ("R5-p2","in",*Bv("mv 02_成果物/A.md 02_成果物/b.md"),"pass",""),
 ("R5-p3","in","Write",{"file_path":VR+"/02_成果物/A.md"},"pass",""),
 # R6：同じコマンドの中で作るリンク（元か行き先が保護しているもの、またはその下）・ln -sf で印を差し替え
 ("R6-1","out",*Bv(f"ln -s {VR} {VO}/L2 && mv {VO}/L2/設定 /tmp/x"),"deny","リンク"),
 ("R6-2","in",*Bv("ln -s . self && mv self/設定 /tmp/x"),"deny","リンク"),
 ("R6-3","in",*Bv("ln -s 設定 s2 && mv s2/config.json /tmp/x"),"deny","リンク"),
 ("R6-4","out",*Bv(f"cd {VW} && ln -s AI坂田 L3 && mv L3/設定 /tmp/x"),"deny","リンク"),
 ("R6-5","in",*Bv("ln -sf /nonexistent 設定/config.json"),"deny","リンク"),
 ("R6-6","in",*Bv("ln -sf /tmp/o.json 00_タスク管理/data/tasks.json"),"deny","リンク"),
 ("R6-7","out",*Bv(f"ln -sf /tmp/o.json {VR}/設定/config.json"),"deny","リンク"),
 ("R6-8","out",*Bv(f"ln -sfn /tmp/x {VR}"),"deny","リンク"),
 ("R6-9","out",*Bv("ln -sfn /tmp/x ~/.ai-bunshin"),"deny","見張りの記録"),
 ("R6-10","in",*Bv("ln -s ../03_インプット 02_成果物/lk2"),"deny","リンク"),
 ("R6-11","in",*Bv("ln -s 03_インプット/a.csv 02_成果物/a_link.csv"),"deny","リンク"),
 ("R6-12","in",*Bv("python3 -c \"import os;os.symlink('設定','s3')\""),"deny","リンク"),
 ("R6-13","in",*Bv("python3 -c \"from pathlib import Path;Path('s4').symlink_to('03_インプット')\""),"deny","リンク"),
 ("R6-14","in",*Bv("ln -s 03_インプット x && echo hi > x/a.csv"),"deny","リンク"),
 ("R6-15","out",*Bv(f"ln -sfn {VR}/設定 {VO}/cfg"),"deny","リンク"),
 ("R6-16","in",*Bv("ln -s ~/.claude/plugins/cache plug"),"deny","プラグインのコピー"),  # プラグインのコピーの規則が先に当たる
 ("R6-p1","in",*Bv("ln -s 02_成果物/a.md 02_成果物/b.md"),"pass",""),
 ("R6-p2","in",*Bv("ln -s /tmp/foo 05_開発/x/link"),"pass",""),
 ("R6-p3","out",*Bv(f"ln -sf ../lib/a.js {VO}/src/a.js"),"pass",""),
 ("R6-p4","out",*Bv("python3 -c \"import os;os.symlink('a','b')\""),"pass",""),
 ("R6-p5","out",*Bv("ln -s ~/workspace/other/proj/src s"),"pass",""),
 # R7：リンク経由の Write・Bash（並びの先頭だけでなく、実体で比べる）
 ("R7-1","in","Write",{"file_path":VR+"/02_成果物/lk/a.csv"},"deny","元データ"),
 ("R7-2","in",*Bv("echo x > 02_成果物/lk/a.csv"),"deny","元データ"),
 ("R7-3","in",*Bv("cp x 02_成果物/lk/"),"deny","元データ"),
 ("R7-4","out","Write",{"file_path":VO+"/inp/a.csv"},"deny","元データ"),
 ("R7-5","out",*Bv("echo x > inp/a.csv"),"deny","元データ"),
 ("R7-p1","in","Write",{"file_path":VR+"/02_成果物/lkok/a.md"},"pass",""),
 ("R7-p2","in",*Bv("cat 02_成果物/lk/a.csv && echo x > 02_成果物/lkok/b.md"),"pass",""),
]
vfail=0
def check_rows(rows):
    global vfail
    for vid,where,tool,inp,want,word in rows:
        got,reason=run_v(tool,inp,where)
        ok=(got==want) and (want!="deny" or word in reason)
        if not ok: vfail+=1; print("V2",vid,"got",got,"want",want,word,"|",reason[:80].replace(VH,"<VH>"))
check_rows(V)
# R5：ハードリンク（見張りの記録 owners.json）。記録は書き直されると別の実体になるので、確かめる直前に作る
_hl=VO+"/rec_hl.json"
os.link(VH+"/.ai-bunshin/owners.json",_hl)
check_rows([("R5-15","out",*Bv(f"echo '{{}}' > {_hl}"),"deny","見張りの記録"),("R5-16","out","Write",{"file_path":_hl},"deny","見張りの記録"),
            ("R5-p4","out",*Bv(f"cat {_hl}"),"pass","")])
# R8：owners.json が読めない（深い入れ子・壊れた JSON など）でも落ちずに、本人のフォルダの中は止める
for nm,txt in [("深い入れ子","["*200000+"]"*200000),("壊れた JSON","{not json"),("null","null"),("owners が文字列",'{"owners": "/x"}'),
               ("入れ子リスト",'{"owners": [["/x"], 5, null, "rel/path"]}'),("BOM","﻿{\"owners\": []}"),("バイナリ","\udcff")]:
    H8=os.path.realpath(tempfile.mkdtemp(prefix="ngr8_")); R8=H8+"/ws/AI坂田"; O8=H8+"/ws/other"
    for d in ["設定","00_タスク管理/data"]: os.makedirs(R8+"/"+d)
    open(R8+"/設定/config.json","w").write("{}"); os.makedirs(O8); os.makedirs(H8+"/.ai-bunshin")
    with open(H8+"/.ai-bunshin/owners.json","w",encoding="utf-8",errors="surrogateescape") as f: f.write(txt)
    for vid,where,c,want,word in [("R8-in",R8,"mv 設定 /tmp/x","deny","正本の移動"),("R8-out→本人",O8,f"mv {R8}/設定 /tmp/x","deny","正本の移動"),
                                  ("R8-out",O8,"mv a b","pass",""),("R8-in-rm",R8,f"{RM} x","deny","削除")]:
        got,reason=run_v("Bash",{"command":c},where,home=H8)
        if got!=want or (want=="deny" and word not in reason): vfail+=1; print("V2",vid,nm,"got",got,"want",want,reason[:60])
# R9：長いコマンドでも遅くならない（55KB で 1 秒未満）
for vid,where,c in [("R9-in","in","python3 x; "*5000),("R9-out","out","python3 x; "*5000),("R9-find","in","find . -name a -print; "*2400),
                    ("R9-py-rename","in","python3 -c \"os.rename('a','b')\"; "*1700)]:
    (got,reason),dt=run_v("Bash",{"command":c},where,timeit=True)
    if got!="pass" or dt>=1.0: vfail+=1; print("V2",vid,"got",got,"秒",round(dt,2),"長さ",len(c))
# --explain "<コマンド>"：判定（deny／pass）と理由の語を出す（記録は書かない）
def explain(c,where="in"):
    base={"in":VR,"out":VO}[where]; env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["HOME"]=VH
    p=subprocess.run(["python3",G,"--explain",c],capture_output=True,text=True,cwd=base,env=env)
    return p.returncode,p.stdout
_log=VR+"/00_タスク管理/data/ng_log.jsonl"; _n=len(open(_log,encoding="utf-8").read().splitlines()) if os.path.exists(_log) else 0
for c,where,want,word in [("mv 03_インプット /tmp/x","in","deny","元データ"),("ls -la","in","pass",""),(f"{RM} -rf build","out","pass",""),
                          (f"{RM} -rf {VR}/03_インプット","out","deny","削除"),("ln -s 設定 s2","in","deny","リンク")]:
    rc,out=explain(c,where)
    if rc!=0 or ("判定："+want) not in out or (word and word not in out): vfail+=1; print("V2 EXPLAIN",repr(c),rc,out[:120])
if (len(open(_log,encoding="utf-8").read().splitlines()) if os.path.exists(_log) else 0)!=_n: vfail+=1; print("V2 EXPLAIN が ng_log に書いた")
fail+=vfail
# ---- T058 の直し（部下D の確かめ：指摘1〜6・8 と、プラグインの規則を区切りごとに見る）----
# 部下D の試し（p1〜p9）で、直す前に失敗することを確かめた行を写した。期待が deny の行は、理由の語まで見る
print("## T058 直し（ヒアドキュメント・起動役・締め切り・ハードリンク・例外・cd のワイルドカード）")
import time as _time
XH=os.path.realpath(tempfile.mkdtemp(prefix="ngfix_")); XW=XH+"/workspace"; XR=XW+"/AI坂田"; XO=XW+"/other/proj"
for d in ["設定","00_タスク管理/data","05_開発/x","02_成果物/共通","03_インプット",".claude/rules",".claude/hooks"]: os.makedirs(XR+"/"+d)
for f,t in [("設定/config.json","{}"),("00_タスク管理/data/tasks.json","{}"),(".claude/rules/ai-bunshin-common.md","x"),(".claude/settings.json","{}"),
            ("CLAUDE.md","x"),("03_インプット/a.csv","a"),("02_成果物/a.md","x")]:
    open(XR+"/"+f,"w").write(t)
os.makedirs(XO+"/src2"); os.makedirs(XH+"/.claude/plugins/cache/x")
os.link(XR+"/03_インプット/a.csv",XO+"/hl_inp.csv"); os.link(XR+"/.claude/settings.json",XO+"/hl_set.json")
os.symlink("loopb",XO+"/loopa"); os.symlink("loopa",XO+"/loopb")
os.symlink(XR+"/.claude",XO+"/cl")
def run_x(tool,inp,where,extra=None,timeit=False):
    base={"in":XR,"out":XO,"ws":XW,"home":XH}.get(where,where)
    env={k:v for k,v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR","NG_GUARD_DEADLINE")}; env["HOME"]=XH; env["CLAUDE_PROJECT_DIR"]=base
    env.update(extra or {})
    t0=_time.time()
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp,"cwd":base}),capture_output=True,text=True,cwd=base,env=env)
    dt=_time.time()-t0
    try: o=json.loads(p.stdout)["hookSpecificOutput"]; got=(o["permissionDecision"],o.get("permissionDecisionReason",""))
    except Exception: got=("pass","")
    if p.returncode!=0: got=("rc%d"%p.returncode,p.stderr[-200:])
    return (got,dt) if timeit else got
run_x("Bash",{"command":"ls"},"in")  # 記録に足す
def Bx(c): return ("Bash",{"command":c})
HD="cat <<'EOF' > 02_成果物/n.md\nhi\nEOF\n"
XF=[
 # 指摘1：ヒアドキュメントの本文を取り除いてから区切る。後ろのコマンドを読む。本文の中の * で誤って止めない
 ("F1-1","in",*Bx(HD+"mv 設定 /tmp/y"),"deny","正本の移動"),
 ("F1-2","in",*Bx(HD+"ln -s 設定 s"),"deny","リンク"),
 ("F1-3","in",*Bx(HD+"cp a.csv 03_インプット"),"deny","元データ"),
 ("F1-4","in",*Bx(HD+"touch 03_インプット/new.csv"),"deny","元データ"),
 ("F1-5","in",*Bx(HD+"mv ../AI坂田 /tmp/x"),"deny","本人のフォルダそのもの"),
 ("F1-6","in",*Bx("python3 - <<'EOF'\nprint(1)\nEOF\nmv 00_タスク管理 /tmp/x"),"deny","正本の移動"),
 ("F1-7","out",*Bx(HD.replace("02_成果物/n.md","notes.md")+f"mv {XR}/設定 /tmp/x"),"deny","正本の移動"),
 ("F1-8","in",*Bx(HD+"unzip -o x.zip -d 03_インプット"),"deny","元データ"),
 ("F1-9","in",*Bx("mkdir -p 02_成果物/x && python3 - <<'EOF'\nfrom pathlib import Path\nfor f in Path('.').rglob(\"*\"): pass\nEOF"),"pass",""),
 ("F1-10","in",*Bx("touch 02_成果物/a.md && python3 - <<'EOF'\nimport glob\nprint(glob.glob('*'))\nEOF"),"pass",""),
 ("F1-11","in",*Bx("cat > 02_成果物/x.md <<'EOF'\nmv 設定 x / ln -s 03_インプット / chmod\nEOF"),"pass",""),
 ("F1-12","in",*Bx("python3 - <<'EOF'\nimport shutil\nshutil.rmtree('03_インプット')\nEOF"),"deny","削除"),  # python3 - の本文は前の版と同じくコードとして読む
 ("F1-13","out",*Bx(f"python3 - <<'EOF'\nimport shutil\nshutil.rmtree('{XR}/03_インプット')\nEOF"),"deny","削除"),
 ("F1-14","in",*Bx("cat <<-'EOF' > 02_成果物/t.md\n\tx\n\tEOF\ntouch 03_インプット/t.csv"),"deny","元データ"),
 # 指摘2：起動役（xargs・timeout・nice・parallel・find -exec）をほどいて、中のコマンドを読む
 ("F2-1","in",*Bx("xargs -I {} cp {} 03_インプット/ < list"),"deny","元データ"),
 ("F2-2","in",*Bx("xargs -n 1 -I {} mv {} 03_インプット/ < list"),"deny","元データ"),
 ("F2-3","in",*Bx("timeout 5 cp a.csv 03_インプット/"),"deny","元データ"),
 ("F2-4","in",*Bx("nice -n 5 cp a.csv 03_インプット/"),"deny","元データ"),
 ("F2-5","in",*Bx("parallel cp {} 03_インプット/ ::: a b"),"deny","元データ"),
 ("F2-6","in",*Bx("find . -maxdepth 1 -name '*.csv' -print0 | xargs -0 -I {} cp {} 03_インプット/"),"deny","元データ"),
 ("F2-7","in",*Bx(f"find {XO}/src2 -name '*.csv' -exec cp {{}} 03_インプット/ \\;"),"deny","元データ"),
 ("F2-8","in",*Bx(f"find {XO}/src2 -name '*.csv' -exec mv {{}} 03_インプット/ \\;"),"deny","元データ"),
 ("F2-9","in",*Bx(f"find {XO}/src2 -name '*.csv' -exec cp {{}} {XR}/03_インプット/ \\;"),"deny","元データ"),
 ("F2-10","in",*Bx("find /tmp -name '*.csv' -exec cp {} 03_インプット/ \\;"),"deny","元データ"),
 ("F2-11","in",*Bx("find 03_インプット -name '*.csv' -exec sed -i '' s/a/b/ {} +"),"deny","元データ"),
 ("F2-12","in",*Bx("env -C 03_インプット touch z.csv"),"deny","元データ"),
 ("F2-p1","in",*Bx("find 03_インプット -name '*.csv' -exec grep -l a {} +"),"pass",""),
 ("F2-p2","in",*Bx("timeout 5 ls 03_インプット"),"pass",""),
 ("F2-p3","in",*Bx("ls 02_成果物/*.md | xargs -I {} grep -l x {}"),"pass",""),
 ("F2-p4","in",*Bx("nice -n 5 python3 x.py > 02_成果物/out.txt"),"pass",""),
 # 指摘4：ハードリンクを作る操作。元が 03_インプット・.claude の設定・印・記録なら、作る時点で止める
 ("F4-1","in",*Bx("ln 03_インプット/a.csv 02_成果物/h && echo x > 02_成果物/h"),"deny","リンク"),
 ("F4-2","in",*Bx("link 03_インプット/a.csv 02_成果物/h2"),"deny","リンク"),
 ("F4-3","in",*Bx("ln .claude/settings.json 02_成果物/s"),"deny","リンク"),
 ("F4-4","in",*Bx("python3 -c \"import os;os.link('03_インプット/a.csv','h3')\""),"deny","リンク"),
 ("F4-5","in",*Bx("cp -l 03_インプット/a.csv 02_成果物/h4"),"deny","リンク"),
 ("F4-6","in",*Bx("cp -s ../03_インプット/a.csv 02_成果物/h5"),"deny","リンク"),
 ("F4-7","in",*Bx("cp -al 03_インプット 02_成果物/h6"),"deny","リンク"),
 ("F4-8","out",*Bx(f"ln {XR}/03_インプット/a.csv h9"),"deny","リンク"),
 ("F4-9","in",*Bx("ln 03_インプット/a.csv /tmp/h10"),"deny","リンク"),
 ("F4-10","in",*Bx("python3 -c \"from pathlib import Path;Path('h11').hardlink_to('設定/config.json')\""),"deny","リンク"),
 ("F4-11","out","Write",{"file_path":XO+"/hl_inp.csv"},"deny","元データ"),     # 外に作ってあるハードリンクへの書き込み
 ("F4-12","out",*Bx("echo x > hl_inp.csv"),"deny","元データ"),
 ("F4-13","out","Write",{"file_path":XO+"/hl_set.json"},"deny","権限・設定"),
 ("F4-14","out",*Bx("echo '{}' > hl_set.json"),"deny","権限・設定"),
 ("F4-p1","in",*Bx("ln 02_成果物/a.md 02_成果物/b.md"),"pass",""),
 ("F4-p2","in",*Bx("cp -l 02_成果物/a.md 02_成果物/c.md"),"pass",""),
 ("F4-p3","out",*Bx("ln ../src2/x y && cp -al src src_bk"),"pass",""),
 # 指摘5：stat が失敗するパス（リンクのループ）
 ("F5-1","in",*Bx(f"mv {XO}/loopa/../../../../AI坂田/設定 /tmp/x"),"deny","読み切れない"),
 ("F5-2","in","Write",{"file_path":XO+"/loopa/x"},"pass",""),
 ("F5-3","out","Write",{"file_path":XO+"/loopa/x"},"pass",""),
 ("F5-4","in",*Bx(f"mkdir -p {XO}/cl/hooks && echo x > {XO}/cl/hooks/x.sh"),"deny","hook"),  # リンク経由で .claude の下に書く
 # 指摘6：cd のワイルドカードを to_paths と同じに解く。当たりが1つならそれ、0個か2個以上なら止める側
 ("F6-1","in",*Bx("cd 03_*/ && touch new.csv"),"deny","元データ"),
 ("F6-2","in",*Bx("cd 設* && mv config.json x"),"deny","正本の移動"),
 ("F6-3","out",*Bx(f"cd {XW}/AI* && {RM} -rf 03_インプット"),"deny","削除"),
 ("F6-4","in",*Bx("cd 0?_インプット && echo x > a.csv"),"deny","元データ"),
 ("F6-5","in",*Bx("pushd 03_* && touch z"),"deny","元データ"),
 ("F6-6","in",*Bx("cd 0* && touch z"),"deny","cd の行き先を読み切れない"),     # 当たりが2個以上
 ("F6-7","in",*Bx("cd nomatch* && touch z"),"pass",""),  # 当たりが0個：cd が失敗して && の後ろは動かない（前の版・部下D の g-p4 と同じ。T058 の決めで通すに変えた）
 ("F6-p1","in",*Bx("cd 02_* && touch new.md"),"pass",""),
 ("F6-p2","in",*Bx("cd 0* && ls"),"pass",""),
 ("F6-p3","in",*Bx("mkdir -p 02_成果物/new && cd 02_成果物/new && touch a.md"),"pass",""),
 # 指摘8：外で、本人のフォルダの親へのリンクは止めない。本人のフォルダの中に親へのリンクを作るのは止める
 ("F8-p1","out",*Bx("ln -s ~ homelink"),"pass",""),
 ("F8-p2","out",*Bx(f"ln -s {XW} wslink"),"pass",""),
 ("F8-1","in",*Bx("ln -s ../../ 02_成果物/up"),"deny","リンク"),
 ("F8-2","out",*Bx(f"ln -s {XR} rlink"),"deny","リンク"),
 # プラグインのコピー：区切りごとに見る（読むだけの区切りのあとの別の場所での cd で止めない。指揮官 10/31 の報告）
 ("FP-p1","in",*Bx("cat ~/.claude/plugins/known_marketplaces.json; echo; cd ~/workspace && git log --oneline -3"),"pass",""),
 ("FP-p2","in",*Bx("ls ~/.claude/plugins/cache/ && cd 02_成果物 && touch a.md"),"pass",""),
 # 「X=~/.claude/plugins; echo hi > $X/a」（変数で受け渡してから書く）は前の版でも止まらない。既知の残り（T092 の ask）
 ("FP-2","in",*Bx("cd ~/.claude/plugins && cp /tmp/x ."),"deny","プラグインのコピー"),
 ("FP-3","in",*Bx("cat ~/.claude/plugins/a | tee ~/.claude/plugins/b"),"deny","プラグインのコピー"),
]
xfail=0
for vid,where,tool,inp,want,word in XF:
    got,reason=run_x(tool,inp,where)
    if got!=want or (want=="deny" and word not in reason): xfail+=1; print("FIX",vid,"got",got,"want",want,word,"|",reason[:70].replace(XH,"<XH>"))
# 指摘5：config.json の形が違っても、外から本人のフォルダを指す操作は止める。開発の置き場所の中のインストールは通す
for nm,cfgtxt in [("[]","[]"),("ng_allow に数",'{"ng_allow":[5]}'),("ng_allow が文字列",'{"ng_allow":"x"}'),("dev がリスト",'{"dev":[]}'),
                  ("path がループ",json.dumps({"dev":{"projects":[{"path":XO+"/loopa"}]}})),("projects に文字列",'{"dev":{"projects":["x"]}}'),("壊れた JSON","{x")]:
    open(XR+"/設定/config.json","w").write(cfgtxt)
    for vid,where,c,want in [("out-rm","out",f"{RM} -rf {XR}/03_インプット","deny"),("out-03","out",f"npm install && echo x > {XR}/03_インプット/a.csv","deny"),
                             ("in-rm","in",f"{RM} x","deny"),("in-dev","in","cd 05_開発/x && npm install","pass"),("in-ls","in","ls","pass")]:
        got,reason=run_x("Bash",{"command":c},where)
        if got!=want: xfail+=1; print("FIX F5-config",nm,vid,"got",got,"want",want)
open(XR+"/設定/config.json","w").write("{}")
# 指摘3：締め切り。cd×1500・python の変数×3000 は 1 秒未満。締め切りを超えたら、中は止める・外は本人のフォルダが文面にあれば止める
for vid,where,c,want in [("F3-cd","in","cd a; "*1500,"pass"),("F3-cd-tail","in","cd a; "*1500+f"cd {XR} && {RM} -rf 03_インプット","deny"),
                         ("F3-py","in","python3 -c \""+"x=Path('a');"*3000+"\"","pass"),("F3-exec","in","find . "+"-exec grep a {} + "*3000,"pass")]:
    (got,reason),dt=run_x("Bash",{"command":c},where,timeit=True)
    if got!=want or dt>=1.0: xfail+=1; print("FIX",vid,"got",got,"want",want,"秒",round(dt,2))
(got,reason)=run_x("Bash",{"command":"cd a; "*600+"touch x"},"in")  # 今いる場所が 1024 文字を超えた：読み切れない
if got!="deny" or "cd の行き先を読み切れない" not in reason: xfail+=1; print("FIX F3-long-cwd",got,reason[:60])
# 締め切り：テストは関数の引数（decide の deadline=）で短くする。本番は環境変数などで変えられない（T058 の直し6）
_sp2=importlib.util.spec_from_file_location("ng_guard_dl",G); DL=importlib.util.module_from_spec(_sp2); _sp2.loader.exec_module(DL)
_saved_env,_saved_cwd=dict(os.environ),os.getcwd()
for vid,where,c,want in [("F3-dl-in","in","ls","deny"),("F3-dl-out","out","ls","pass"),("F3-dl-out-mention","out",f"ls {XR}/02_成果物","deny"),
                         ("F3-dl-out-tilde","out","ls ~/workspace/AI坂田/02_成果物","deny")]:
    base={"in":XR,"out":XO}[where]
    os.environ["HOME"]=XH; os.environ["CLAUDE_PROJECT_DIR"]=base; os.chdir(base); DL._SEEN["root"]="unset"
    d,label,_w,_r,_t,fell=DL.decide(json.dumps({"tool_name":"Bash","tool_input":{"command":c},"cwd":base}),deadline=1e-6)
    got="deny" if d else "pass"
    if got!=want or not fell or (want=="deny" and "時間内" not in (label or "")): xfail+=1; print("FIX",vid,"got",got,"want",want,fell,label)
os.environ.clear(); os.environ.update(_saved_env); os.chdir(_saved_cwd)
if DL.deadline_seconds(100)!=5.0 or DL.deadline_seconds(0.5)!=0.5 or DL.deadline_seconds("abc")!=5.0 or DL.deadline_seconds(-1)!=5.0:
    xfail+=1; print("FIX 締め切りの秒の読み方")
got,reason=run_x("Bash",{"command":"ls"},"in",extra={"NG_GUARD_DEADLINE":"0.000001"})  # 環境変数では短くならない（本番では読まない）
if got!="pass": xfail+=1; print("FIX NG_GUARD_DEADLINE を読んでいる",got,reason[:60])
fail+=xfail
# T059：AI が自分の制限（config の ng_allow・maintainer、CLAUDE.md の「許可する例外」）を Write・Edit で書き換えるのを止める
print("## T059 自分の制限の書き換え")
CFGP=os.path.join(R,"設定","config.json"); CLP=os.path.join(R,"CLAUDE.md")
CFG0={"owner":"坂田","name":"x","ng_allow":["^rm x$"],"maintainer":False,"dev":{"default_mode":"local","projects":[]}}
CFG0T=json.dumps(CFG0,ensure_ascii=False,indent=2)
def setcfg(d=CFG0T):
    open(CFGP,"w",encoding="utf-8").write(d if isinstance(d,str) else json.dumps(d,ensure_ascii=False,indent=2))
CL0="# 本人設定\n\n## 基本\n\n- 呼び方：坂田さん\n\n## 許可する例外（NG のうち、本人が許可したもの）\n\n- （まだなし）\n\n## 育ったルール\n\n| 日付 | ルール |\n|---|---|\n| （まだなし） | |\n"
def setcl(t=CL0): open(CLP,"w",encoding="utf-8").write(t)
def cfgw(**kw):
    d=json.loads(CFG0T); d.update(kw); return json.dumps(d,ensure_ascii=False,indent=2)
EXC_OLD="- （まだなし）\n\n## 育ったルール"
T59=[
 # --- config.json：止める ---
 ("cfg","W ng_allow に足す","Write",{"file_path":CFGP,"content":cfgw(ng_allow=["^rm x$","^git push"])},"STOP"),
 ("cfg","W ng_allow を空にする（変更）","Write",{"file_path":CFGP,"content":cfgw(ng_allow=[])},"STOP"),
 ("cfg","W maintainer を true","Write",{"file_path":CFGP,"content":cfgw(maintainer=True)},"STOP"),
 ("cfg","W maintainer を文字列 'false'（bool では True になる）","Write",{"file_path":CFGP,"content":cfgw(maintainer="false")},"STOP"),
 ("cfg","W ng_allow のキーを消す","Write",{"file_path":CFGP,"content":json.dumps({k:v for k,v in CFG0.items() if k!="ng_allow"})},"STOP"),
 ("cfg","W キー名を \\u エスケープで書く","Write",{"file_path":CFGP,"content":'{"ng\\u005fallow": ["^rm x$", "."], "maintainer": false}'},"STOP"),
 ("cfg","W 別の道（./）で指す","Write",{"file_path":R+"/設定/./config.json","content":cfgw(maintainer=True)},"STOP"),
 ("cfg","W 設定/../設定/config.json","Write",{"file_path":R+"/設定/../設定/config.json","content":cfgw(maintainer=True)},"STOP"),
 ("cfg","W 内容なし（確かめられない）","Write",{"file_path":CFGP},"STOP"),
 ("cfg","E maintainer を true","Edit",{"file_path":CFGP,"old_string":'"maintainer": false',"new_string":'"maintainer": true'},"STOP"),
 ("cfg","E ng_allow に足す","Edit",{"file_path":CFGP,"old_string":'"^rm x$"',"new_string":'"^rm x$", "."'},"STOP"),
 ("cfg","E replace_all","Edit",{"file_path":CFGP,"old_string":'false',"new_string":'true',"replace_all":True},"STOP"),
 ("cfg","E 見つからない old_string（確かめられない）","Edit",{"file_path":CFGP,"old_string":'zzz',"new_string":'yyy'},"STOP"),
 ("cfg","E new_string が無い","Edit",{"file_path":CFGP,"old_string":'"name"'},"STOP"),
 ("cfg","ME maintainer を true","MultiEdit",{"file_path":CFGP,"edits":[{"old_string":'"name": "x"',"new_string":'"name": "y"'},{"old_string":'"maintainer": false',"new_string":'"maintainer": true'}]},"STOP"),
 # --- config.json：通す ---
 ("cfg","W ほかのキーだけ変える","Write",{"file_path":CFGP,"content":cfgw(name="y",owner="佐藤")},"pass"),
 ("cfg","W キーの順や字下げだけ変える","Write",{"file_path":CFGP,"content":json.dumps(dict(reversed(list(CFG0.items()))),ensure_ascii=False)},"pass"),
 ("cfg","W dev を足す","Write",{"file_path":CFGP,"content":cfgw(dev={"default_mode":"git","projects":[{"name":"a","mode":"git","path":"/x"}]})},"pass"),
 ("cfg","W 読めない JSON にする（ng_allow が見張りから消える＝変更）","Write",{"file_path":CFGP,"content":"{x"},"STOP"),
 ("cfg","E ほかのキーを変える","Edit",{"file_path":CFGP,"old_string":'"name": "x"',"new_string":'"name": "z"'},"pass"),
 ("cfg","ME ほかのキーを変える","MultiEdit",{"file_path":CFGP,"edits":[{"old_string":'"name": "x"',"new_string":'"name": "z"'},{"old_string":'"owner": "坂田"',"new_string":'"owner": "坂田 K"'}]},"pass"),
 # --- CLAUDE.md ---
 ("cl","W 許可する例外に足す","Write",{"file_path":CLP,"content":CL0.replace(EXC_OLD,"- git push を許可\n\n## 育ったルール")},"STOP"),
 ("cl","W 許可する例外の節を消す","Write",{"file_path":CLP,"content":CL0.replace("## 許可する例外（NG のうち、本人が許可したもの）\n\n- （まだなし）\n\n","")},"STOP"),
 ("cl","W 見出しの名前を変える","Write",{"file_path":CLP,"content":CL0.replace("許可する例外","許可する 例外")},"STOP"),
 ("cl","W 内容なし","Write",{"file_path":CLP},"STOP"),
 ("cl","E 許可する例外に足す","Edit",{"file_path":CLP,"old_string":EXC_OLD,"new_string":"- rm を許可\n\n## 育ったルール"},"STOP"),
 ("cl","E 次の見出しを消して節をのばす","Edit",{"file_path":CLP,"old_string":"## 育ったルール\n","new_string":""},"STOP"),
 ("cl","E 見出しを別の名前にする","Edit",{"file_path":CLP,"old_string":"## 許可する例外（","new_string":"## 例外（"},"STOP"),
 ("cl","ME 許可する例外に足す","MultiEdit",{"file_path":CLP,"edits":[{"old_string":"坂田さん","new_string":"坂田さん様"},{"old_string":EXC_OLD,"new_string":"- 全部\n\n## 育ったルール"}]},"STOP"),
 ("cl","E 見つからない old_string","Edit",{"file_path":CLP,"old_string":"zzz","new_string":"yyy"},"STOP"),
 ("cl","E 別の道（./）で指す","Edit",{"file_path":R+"/./CLAUDE.md","old_string":EXC_OLD,"new_string":"- 全部\n\n## 育ったルール"},"STOP"),
 ("cl","W 育ったルールだけ変える","Write",{"file_path":CLP,"content":CL0.replace("| （まだなし） | |","| 2026-11-01 | 新しいルール |")},"pass"),
 ("cl","W 基本だけ変える","Write",{"file_path":CLP,"content":CL0.replace("坂田さん","さかた")},"pass"),
 ("cl","E 育ったルールを変える","Edit",{"file_path":CLP,"old_string":"| （まだなし） | |","new_string":"| 2026-11-01 | 新しいルール |"},"pass"),
 ("cl","E 基本を変える","Edit",{"file_path":CLP,"old_string":"呼び方：坂田さん","new_string":"呼び方：さかたさん"},"pass"),
 ("cl","ME 育ったルールと基本を変える","MultiEdit",{"file_path":CLP,"edits":[{"old_string":"坂田さん","new_string":"さかた"},{"old_string":"| （まだなし） | |","new_string":"| 1 | 2 |"}]},"pass"),
 ("cl","W 新しい節を足す（許可する例外は同じ）","Write",{"file_path":CLP,"content":CL0+"\n## 新しい節\n\n- a\n"},"pass"),
]
for kind,nm,tool,inp,want in T59:
    setcfg(); setcl()
    got=run(tool,inp)
    if got!=want: fail+=1; print("T059",kind,nm,"got",got,"want",want)
# まだ無いファイルの新規作成は通す（setup が使う）。ng_allow・maintainer・許可する例外を含んでいても、新規作成は通す
R2=tempfile.mkdtemp(prefix="ngtest2_"); os.makedirs(os.path.join(R2,"設定")); os.makedirs(os.path.join(R2,"00_タスク管理","data"))
open(os.path.join(R2,"00_タスク管理","data","tasks.json"),"w").write("{}")
def run2(tool,inp):
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp}),capture_output=True,text=True,cwd=R2,env={**os.environ,"CLAUDE_PROJECT_DIR":R2})
    return "STOP" if "deny" in p.stdout else "pass"
for nm,tool,inp in [("config.json 新規","Write",{"file_path":R2+"/設定/config.json","content":CFG0T}),
                    ("config.json 新規（ng_allow・maintainer 入り）","Write",{"file_path":R2+"/設定/config.json","content":cfgw(maintainer=True,ng_allow=["."])}),
                    ("CLAUDE.md 新規","Write",{"file_path":R2+"/CLAUDE.md","content":CL0.replace(EXC_OLD,"- x\n\n## 育ったルール")})]:
    if run2(tool,inp)!="pass": fail+=1; print("T059 新規作成が止まった",nm)
# 本人の許可する例外（ng_allow）では外れない
for nm,tool,inp in [("config","Write",{"file_path":CFGP,"content":cfgw(maintainer=True)}),("CLAUDE.md","Write",{"file_path":CLP,"content":CL0.replace(EXC_OLD,"- x\n\n## 育ったルール")})]:
    setcfg(cfgw(ng_allow=["."])); setcl()
    if run(tool,inp)!="STOP": fail+=1; print("T059 ng_allow で外れた",nm)
# 読めない config.json（壊れた JSON）に ng_allow を入れる Write は止める（今は {} として扱われている＝足せば緩む）
setcfg("{x"); setcl()
if run("Write",{"file_path":CFGP,"content":cfgw(ng_allow=["."])})!="STOP": fail+=1; print("T059 壊れた config に ng_allow を足せた")
setcfg("{x")  # 今も読めない config.json を、別の読めない形・ng_allow の無い形にする Write は通す（見張りの見え方は変わらない）
for nm,c in [("別の読めない形","{y"),("ng_allow の無い JSON",'{"name":"a"}')]:
    if run("Write",{"file_path":CFGP,"content":c})!="pass": fail+=1; print("T059 読めない config からの変更が止まった",nm)
setcfg("{}")  # 後ろのテストのために戻す
print(f"失敗 {fail} 件"); sys.exit(1 if fail else 0)

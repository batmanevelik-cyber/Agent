package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMain(m *testing.M){sum:=sha256.Sum256(payload);payloadDigest=hex.EncodeToString(sum[:]);os.Exit(m.Run())}

func TestPayloadChecksumRejectsTampering(t *testing.T){
	if !payloadOK(){t.Fatal("valid payload rejected")};payload[0]^=1
	if payloadOK(){t.Fatal("modified payload accepted")};payload[0]^=1
}

func TestMissingInstallationCannotCreateAnAccount(t *testing.T){
	dir:=t.TempDir();if _,err:=choosePython(dir);err==nil{t.Fatal("missing installation accepted")}
	if _,err:=os.Stat(filepath.Join(dir,"current.json"));!os.IsNotExist(err){t.Fatal("unexpected installation mutation")}
}

func TestExistingUnicodeInstallationAndStopRequest(t *testing.T){
	python:=os.Getenv("ALPHA50X_TEST_PYTHON");if python==""{t.Fatal("test interpreter is required")}
	dir:=filepath.Join(t.TempDir(),"Alpha50X Тест spaces");os.MkdirAll(filepath.Join(dir,"data"),0700)
	raw,_:=json.Marshal(map[string]string{"python":python});os.WriteFile(filepath.Join(dir,"current.json"),raw,0600)
	chosen,err:=choosePython(dir);if err!=nil||chosen!=python{t.Fatal("interpreter selection failed",err)}
	if err=requestStop(dir);err!=nil{t.Fatal(err)}
	raw,err=os.ReadFile(filepath.Join(dir,"data","update-request.json"));if err!=nil{t.Fatal(err)}
	var request struct{Action string `json:"action"`;Requested int64 `json:"requested_ms"`};json.Unmarshal(raw,&request)
	if request.Action!="shutdown_for_update"||time.Now().UnixMilli()-request.Requested>2000{t.Fatal("invalid update handoff")}
	if err=waitForPrevious(python,dir,time.Second,&bytes.Buffer{});err!=nil{t.Fatal(err)}
}

func TestActualServiceLockPreventsUpdateUntilReleased(t *testing.T){
	python:=os.Getenv("ALPHA50X_TEST_PYTHON");dir:=t.TempDir();os.MkdirAll(filepath.Join(dir,"data"),0700)
	script:=`import os,sys
f=open(sys.argv[1],'w+b');f.write(b'0');f.flush();f.seek(0)
if os.name=='nt':
 import msvcrt
 msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
print('LOCKED',flush=True)
sys.stdin.buffer.read(1)
f.close()
`
	cmd:=exec.Command(python,"-c",script,filepath.Join(dir,"data","service.lock"));input,_:=cmd.StdinPipe();output,_:=cmd.StdoutPipe()
	if err:=cmd.Start();err!=nil{t.Fatal(err)}
	defer func(){input.Close();cmd.Wait()}()
	scanner:=bufio.NewScanner(output);if !scanner.Scan()||scanner.Text()!="LOCKED"{t.Fatal("test process could not hold the service lock")}
	if err:=waitForPrevious(python,dir,300*time.Millisecond,&bytes.Buffer{});err==nil{t.Fatal("live service lock accepted")}
	input.Close();if err:=cmd.Wait();err!=nil{t.Fatal(err)}
	if err:=waitForPrevious(python,dir,time.Second,&bytes.Buffer{});err!=nil{t.Fatal("released service lock rejected",err)}
}

func TestUpdaterArgumentsKeepSpacesAndShellCharactersLiteral(t *testing.T){
	python:=os.Getenv("ALPHA50X_TEST_PYTHON");dir:=t.TempDir();script:=filepath.Join(dir,"argument test.py")
	os.WriteFile(script,[]byte("import json,sys;print(json.dumps(sys.argv[1:],ensure_ascii=False))"),0600)
	target:="Път с интервали & literal";var output bytes.Buffer
	if err:=runUpdate(python,script,target,&output);err!=nil{t.Fatal(err)}
	var args []string;if err:=json.Unmarshal([]byte(strings.TrimSpace(output.String())),&args);err!=nil{t.Fatal(err)}
	if len(args)!=3||args[0]!="--target"||args[1]!=target||args[2]!="--use-current-python"{t.Fatal("arguments changed",args)}
}

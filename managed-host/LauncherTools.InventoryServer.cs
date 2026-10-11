using System.IO.Pipes;
using System.Text;
using System.Text.Json.Nodes;
using System.Diagnostics;

internal static partial class LauncherTools
{
    // Owned by one GUI session, not a network listener or game service.
    static async Task InventoryServer(string[] args)
    {
        Root=Path.GetFullPath(Option(args,"--root",Directory.GetCurrentDirectory()));
        Db=Path.GetFullPath(Option(args,"--database",Path.Combine(Root,"adapter_data","game.db")));
        CatalogRoot=Path.GetFullPath(Option(args,"--catalog-root",Root));
        var pipe=Option(args,"--pipe");Require(pipe.Length is >=1 and <=180,"Invalid inventory server pipe name");
        using var owner=int.TryParse(Option(args,"--owner-pid"),out var pid)?Process.GetProcessById(pid):null;
        using var lifetime=new CancellationTokenSource();
        var ownerWatch=Task.Run(async()=>{
            while(!lifetime.IsCancellationRequested){
                if(owner is not null&&owner.HasExited){lifetime.Cancel();return;}
                try{await Task.Delay(500,lifetime.Token);}catch(OperationCanceledException){return;}
            }
        });
        try{
            while(!lifetime.IsCancellationRequested){
                using var server=new NamedPipeServerStream(pipe,PipeDirection.InOut,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);
                using var idle=CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);idle.CancelAfter(TimeSpan.FromMinutes(2));
                try{await server.WaitForConnectionAsync(idle.Token);}catch(OperationCanceledException){break;}
                try{
                    using var reader=new StreamReader(server,Encoding.UTF8,false,4096,true);
                    using var writer=new StreamWriter(server,new UTF8Encoding(false),4096,true){AutoFlush=true};
                    using var readLimit=CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);readLimit.CancelAfter(TimeSpan.FromSeconds(30));
                    var read=reader.ReadLineAsync();
                    var ready=await Task.WhenAny(read,Task.Delay(Timeout.Infinite,readLimit.Token));
                    if(ready!=read)continue;
                    var line=await read;if(string.IsNullOrWhiteSpace(line))continue;
                    var shutdown=false;JsonObject response;
                    try{
                        Require(line.Length<=8*1024*1024,"Inventory request too large");
                        var request=JsonNode.Parse(line)!.AsObject();
                        var requestArgs=request["args"]!.AsArray().Select(x=>x!.GetValue<string>()).ToArray();
                        // A resident process never changes its root/database between calls.
                        foreach(var (key,path) in new[]{("--root",Root),("--database",Db),("--catalog-root",CatalogRoot)})
                            Require(Path.GetFullPath(Option(requestArgs,key,path)).Equals(path,StringComparison.OrdinalIgnoreCase),"Inventory server scope mismatch: "+key);
                        var operation=requestArgs.FirstOrDefault()??"";
                        JsonNode result;
                        if(operation=="shutdown"){shutdown=true;result=Obj(new{status="closing"});}
                        else if(operation=="server-info")result=Obj(new{status="ready"});
                        else result=InventoryOperation(requestArgs,true);
                        response=Obj(new{ok=true,result,server_pid=Environment.ProcessId,catalog_loads=CatalogLoads});
                    }catch(Exception ex){response=Obj(new{ok=false,error=ex.ToString(),server_pid=Environment.ProcessId,catalog_loads=CatalogLoads});}
                    await writer.WriteLineAsync(response.ToJsonString());if(shutdown)break;
                }catch(IOException){ /* A disconnected caller is never automatically replayed. */ }
            }
        }finally{lifetime.Cancel();await ownerWatch;}
    }
}

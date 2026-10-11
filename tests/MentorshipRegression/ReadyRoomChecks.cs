using System.Buffers.Binary;
using System.Collections;
using System.Reflection;
using System.Text;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static object ReadyAuxiliary(Fixture f, object world, byte game)
    {
        var session = Activator.CreateInstance(SessionType, nonPublic: true)!;
        Check(InvokeMentorship<bool>(f.Service, "TryRestoreAuxiliaryGameSession", Character(world).Name,
            "127.0.0.1", session), "auxiliary inventory binds to the authenticated world generation");
        Set(session, "ArenaGameType", game);
        var active = typeof(NetworkAdapterService).GetField("_activeArenaSessions", PrivateInstance)!.GetValue(f.Service)!;
        active.GetType().GetMethod("TryAdd")!.Invoke(active, [Id(session), session]);
        return session;
    }

    private static IList ReadyPending(object session) => (IList)Get(session, "PendingSessionBroadcasts")!;
    private static object[] ReadyMessages(object source, ushort opcode) => ReadyPending(source).Cast<object>()
        .Where(row => (ushort)Get(row, "Opcode")! == opcode).ToArray();

    private static async Task CheckReadyRoomInventoryAsync()
    {
        await using var f = await Fixture.CreateAsync();
        var world = f.Teacher;
        await f.ExecuteAsync("UPDATE Characters SET CurrentHp=100, CurrentMp=10, PetVariant=1, EquippedPetItemCode=15000001 WHERE Id=$id; "
            + "INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,UpdatedAt) VALUES($id,14000001,5,'test'),($id,15000001,1,'test'),($id,15000002,1,'test') "
            + "ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET Quantity=excluded.Quantity", ("$id",Character(world).Id));
        Set(world,"Character",(await f.Database.GetCharacterByIdAsync(Character(world).Id))!);
        var host = ReadyAuxiliary(f,world,4); var guest = ReadyAuxiliary(f,f.Student,4);
        var create = new ArenaCreateRequest(new byte[44],"Inventory room","",0,0,0,0,0,0);
        var room = InvokeMentorship<object>(f.Service,"CreateArenaRoom",host,create);
        Check(InvokeMentorship<bool>(f.Service,"TryJoinArenaRoom",guest,checked((ushort)(int)Get(room,"Id")!),"",null),"inventory peer joins");
        Task<byte[]?> Send(object member, ushort op, byte[] bytes) => Dispatch(f,member,op,bytes,"ArenaAdapter");
        await Send(host,0xCF70,new byte[4]); await Send(guest,0xCF70,new byte[4]);
        foreach(var op in new ushort[]{0xC378,0xC42F,0xC44B,0xC3CB,0xC3E7,0xC409})
            Check(await Send(host,op,op == 0xC409 ? new byte[]{10,0,0,0} : op==0xC3E7 ? new byte[4] : []) is {Length: > 8},"auxiliary inventory page completes "+op);
        var list=(await Send(host,0xC42F,[]))!;
        var foodRow=Enumerable.Range(0,BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(10)))
            .First(i=>BinaryPrimitives.ReadUInt32LittleEndian(list.AsSpan(12+i*8))==14000001);
        var handle=BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(16+foodRow*8));
        var use=new byte[8];BinaryPrimitives.WriteUInt32LittleEndian(use,14000001);
        BinaryPrimitives.WriteUInt32LittleEndian(use.AsSpan(4),handle);
        ReadyPending(host).Clear();
        var used=(await Send(host,0xC46D,use))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(used.AsSpan(8))==1,"auxiliary food commits with world transaction ownership");
        var saved=(await f.Database.GetCharacterByIdAsync(Character(host).Id))!;
        Check(saved.Items.Single(item=>item.ItemCode==14000001).Quantity==4 && saved.CurrentHp>100,"food quantity and health commit together");
        Check(ReferenceEquals(Character(host),Character(world)),"world and auxiliary share the committed character snapshot");
        Check(ReadyMessages(host,0xCF72).Length==2,"food refresh reaches both initialized room viewers");
        Check(ReadyMessages(host,0xCF72).All(row=>BinaryPrimitives.ReadUInt16LittleEndian(((byte[])Get(row,"Payload")!).AsSpan(92))==0),"resource-only refresh preserves pet construction");
        byte[] Equipment(uint pet)
        {
            var bytes=new byte[136];Character(host).Appearance.CopyTo(bytes,96);
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(88),pet);
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(92),Character(host).EquippedPetItemCode);
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(124),pet);return bytes;
        }
        ReadyPending(host).Clear();
        var changed=(await Send(host,0xC47D,Equipment(15000002)))!;
        Check(BinaryPrimitives.ReadUInt16LittleEndian(changed.AsSpan(8))==2000,"auxiliary pet selection completes");
        Check(Character(host).EquippedPetItemCode==15000002 && Character(world).EquippedPetItemCode==15000002,"both connections retain the selected pet");
        Check(ReadyMessages(host,0xCF72).Length==2 && ReadyMessages(host,0xCF72).All(row=>BinaryPrimitives.ReadUInt16LittleEndian(((byte[])Get(row,"Payload")!).AsSpan(92))==1),"pet replacement refreshes existing room actors");
        for(var i=0;i<4;i++)
        {
            Check(await Send(host,0xC378,[]) is {Length:>8},"reopened backpack restores its summary "+i);
            Check((await Send(host,0xC42F,[])) is {Length:>12},"reopened backpack keeps items "+i);
            Check((await Send(host,0xC44B,[])) is {Length:>12},"reopened backpack keeps pets "+i);
        }
        ReadyPending(world).Clear();
        var worldChanged=(await Dispatch(f,world,0xC47D,Equipment(15000001)))!;
        Check(BinaryPrimitives.ReadUInt16LittleEndian(worldChanged.AsSpan(8))==2000 && Character(host).EquippedPetItemCode==15000001,"world-route equipment updates auxiliary state");
        Check(ReadyMessages(world,0xCF72).Length==2,"world-route mutation refreshes the ready room");
        foreach(var actor in new[]{host,guest})
        {
            var endpoint=new byte[20];Encoding.ASCII.GetBytes("127.0.0.1").CopyTo(endpoint,0);
            BinaryPrimitives.WriteUInt32LittleEndian(endpoint.AsSpan(16),actor==host?3534u:3535u);
            await Send(actor,0xCFD1,endpoint);await Send(actor,0xCF7D,[1,0,0,0]);
        }
        Check(await Send(host,0xCFEB,[0,0,1,0]) is {Length:808},"game data builds after inventory mutations");
        await Send(host,0xCFD5,[1,0,0,0]);await Send(guest,0xCFD5,[1,0,0,0]);
        await Send(guest,0xCF7F,[]);
        Check(await Send(host,0xCF7F,[]) is {Length:8} && (bool)Get(room,"Started")!,"inventory completion permits the room to start");
        Check(await Send(host,0xC47D,Equipment(15000002)) is null,"active combat excludes ready-room equipment mutations");
        InvokeMentorship<object?>(f.Service,"RemoveArenaRoomMember",host,null);
        InvokeMentorship<object?>(f.Service,"RemoveArenaRoomMember",guest,null);
        var next=InvokeMentorship<object>(f.Service,"CreateArenaRoom",host,create);
        Check((int)Get(next,"Id")! != (int)Get(room,"Id")! && await Send(host,0xC378,[]) is {Length:>8},"same connection creates a new room with intact inventory");
        var currentWorldId=(string)Get(host,"AuxiliaryWorldSessionId")!;
        Set(host,"AuxiliaryWorldSessionId","retired");
        Check(await Send(host,0xC42F,[]) is null,"retired world generation cannot operate inventory");
        Set(host,"AuxiliaryWorldSessionId",currentWorldId);
        await f.ExecuteAsync("UPDATE Accounts SET ActiveSessionId='retired' WHERE Id=$id",("$id",Character(host).AccountId));
        Check(BinaryPrimitives.ReadUInt16LittleEndian((await Send(host,0xC47D,Equipment(15000002)))!.AsSpan(8))==0,"database ownership is revalidated at transaction commit");
    }

    private static async Task CheckEntertainmentRoomUpdatesAsync()
    {
        await using var f=await Fixture.CreateAsync();
        var host=ReadyAuxiliary(f,f.Teacher,1);var guest=ReadyAuxiliary(f,f.Student,1);
        var create=new byte[44];Encoding.ASCII.GetBytes("Live record").CopyTo(create,0);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24),200);
        Task<byte[]?> Send(object actor,ushort op,byte[] bytes)=>Dispatch(f,actor,op,bytes,"ArenaAdapter");
        await Send(host,0xCF6C,create);
        var roomId=(int)Get(host,"EntertainmentRoomId")!;
        var rooms=(IDictionary)typeof(NetworkAdapterService).GetField("_entertainmentRooms",PrivateInstance)!.GetValue(f.Service)!;
        var room=rooms[roomId]!;
        var enter=new byte[12];BinaryPrimitives.WriteUInt16LittleEndian(enter,20);BinaryPrimitives.WriteUInt16LittleEndian(enter.AsSpan(2),(ushort)roomId);
        await Send(guest,0xCF75,enter);
        for(uint level=0;level<=4;level++)
        {
            var settings=new byte[36];Encoding.ASCII.GetBytes("Live record").CopyTo(settings,0);
            BinaryPrimitives.WriteUInt32LittleEndian(settings.AsSpan(32),level);ReadyPending(host).Clear();
            var response=(await Send(host,0xCF79,settings))!;
            Check(BinaryPrimitives.ReadUInt32LittleEndian(response.AsSpan(40))==level && (ushort)Get(Get(room,"CreateRequest")!,"Level")! == level,"room difficulty authority changes "+level);
            Check(ReadyMessages(host,0xCF7A).Length==1 && ((byte[])Get(ReadyMessages(host,0xCF7A)[0],"Payload")!).AsSpan().SequenceEqual(response.AsSpan(8)),"existing member sees the same settings "+level);
            Check(await Send(guest,0xCF79,settings) is null,"only the owner edits settings");
            var future=(byte[])await (Task<byte[]>)typeof(NetworkAdapterService).GetMethod("BuildEntertainmentEnterResponseAsync",PrivateInstance)!.Invoke(f.Service,[room,CancellationToken.None])!;
            Check(future[1]==level,"later arrival receives current difficulty "+level);
            BinaryPrimitives.WriteUInt32LittleEndian(settings.AsSpan(32),uint.MaxValue);
            Check(await Send(host,0xCF79,settings) is null,"invalid difficulty is rejected atomically");
        }
        async Task Round(uint hostScore,uint guestScore,bool update)
        {
            Set(guest,"EntertainmentReady",true);var board=(await Send(host,0xCFE5,[]))!;
            Check(board[95]==EntertainmentProtocol.BuildGameData(4)[87],"next board uses updated difficulty");
            await Send(host,0xCF7F,[]);await Send(guest,0xCF7F,[]);
            var round=(Guid)Get(room,"RoundId")!;
            var scores=(IDictionary)Get(room,"ScoresBySession")!;scores[Id(host)]=hostScore;scores[Id(guest)]=guestScore;
            Set(room,"StartedUtc",DateTime.UtcNow.AddSeconds(-105));
            InvokeMentorship<object>(f.Service,"CollectEntertainmentDeadlines",DateTime.UtcNow);
            ReadyPending(host).Clear();ReadyPending(guest).Clear();
            Check(await Send(host,0xCF85,[]) is {Length:144},"two-member settlement completes");
            Check(InvokeMentorship<bool>(f.Service,"IsCurrentEntertainmentDelivery",host,(Guid?)round),"current room update remains deliverable");
            Check(!InvokeMentorship<bool>(f.Service,"IsCurrentEntertainmentDelivery",host,(Guid?)Guid.NewGuid()),"another round update is excluded at final delivery");
            var messages=ReadyMessages(host,0xCF7A);
            Check(messages.Length==(update?2:0),"record changes publish exactly once to current members");
            foreach(var row in messages)
            {
                var data=(byte[])Get(row,"Payload")!;
                Check(data.Length==72 && BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(36))==0x31305245
                    && BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(40))==roomId
                    && BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(44))==Math.Max(hostScore,guestScore)
                    && (Guid)Get(row,"EntertainmentRoundId")! ==round,"record includes exact room, score and round identity");
                Check(Encoding.ASCII.GetString(data,48,24).TrimEnd('\0')==(hostScore>guestScore?"Teacher":"Student"),"record identifies its actual holder");
            }
            ReadyPending(host).Clear();
            await Send(host,0xCF85,[]);await Send(guest,0xCF85,[]);
            Check(ReadyMessages(host,0xCF7A).Length==0 && ReadyMessages(guest,0xCF7A).Length==0,"duplicate settlement preserves record publication idempotency");
        }
        await Round(4558,3000,true);await Round(100,200,false);await Round(5000,6000,true);
    }
}

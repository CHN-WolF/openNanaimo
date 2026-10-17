using OpenNanaimo.Adapter.Services;
using Microsoft.Data.Sqlite;
using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

internal static partial class LauncherTools
{
    sealed record InventoryPlan(System.Text.Json.Nodes.JsonObject State,long[] Clothes,long[] Pets,System.Collections.Generic.Dictionary<long,(long Upgrade,long[] Gems)> PetValues);
    static InventoryPlan ValidateInventory(System.Text.Json.Nodes.JsonObject state,IEnumerable<System.Text.Json.Nodes.JsonObject> originalCards)
    {
        state=(System.Text.Json.Nodes.JsonObject)Clone(state);var shop=state["shop"]??throw new InvalidDataException("Missing shop");var equip=A(shop,"equipped").Select(x=>Num(x)).ToArray();Require(equip.Length==5,"profile needs five equipment slots");
        var clothes=A(state,"clothing").Select(x=>Num(x)).Where(x=>x!=0).Concat(equip).Append(N(shop,"effect")).Where(x=>x!=0).Distinct().ToArray();
        var pets=Objects(state,"pets").Select(x=>N(x,"code")).Append(N(shop,"selected_pet")).Where(x=>x!=0).Distinct().ToArray();Require(clothes.Length<=256&&pets.Length<=128,"inventory capacity exceeded");Require(clothes.All(Catalog["clothing"].ContainsKey),"unknown clothing");Require(pets.All(Catalog["pets"].ContainsKey),"unknown pet");
        var petValues=new Dictionary<long,(long,long[])>();var petRows=Objects(state,"pets").ToDictionary(x=>N(x,"code"));foreach(var code in pets){var meta=Catalog["pets"][code];petRows.TryGetValue(code,out var row);var gems=A(row,"gems").Take(3).Select(x=>Num(x)).Concat(new long[3]).Take(3).ToArray();for(int i=0;i<3;i++){if(i>=N(meta,"slot_count"))gems[i]=0;else Require(gems[i]==0||Catalog["gems"].ContainsKey(gems[i]),"unknown pet gem");}var upgrade=N(row,"upgrade_material");Require(upgrade==0||upgrade==N(meta,"upgrade_material"),"invalid upgrade material");petValues[code]=(upgrade,gems);}
        var games=Objects(state,"game_items").ToArray();Require(games.Select(x=>N(x,"code")).Distinct().Count()==games.Length,"duplicate game item code");foreach(var row in games){Require(Catalog["game"].ContainsKey(N(row,"code"))&&N(row,"count") is >=1 and <=65535,"invalid game item/count");row["carrier"]=S(Catalog["game"][N(row,"code")],"carrier","stackable");}
        var protectedCards=originalCards.Where(x=>!Catalog["cards"].ContainsKey(N(x,"code"))).ToDictionary(x=>N(x,"code"),x=>N(x,"count"));var cards=new System.Text.Json.Nodes.JsonArray();var seen=new HashSet<long>();foreach(var row in Objects(state,"cards")){long code=N(row,"code"),count=N(row,"count");Require(seen.Add(code),"duplicate card code");if(Catalog["cards"].ContainsKey(code)){Require(count is >=1 and <=255,"card count out of range");cards.Add(Obj(new{code,count}));}else Require(protectedCards.TryGetValue(code,out var old)&&old==count,"uncatalogued card is read-only; cannot add or change its stored quantity");}foreach(var(code,count) in protectedCards.OrderBy(x=>x.Key))cards.Add(Obj(new{code,count}));state["cards"]=cards;
        var furniture=Objects(state,"furniture").ToArray();Require(furniture.Length<=254&&furniture.Count(x=>B(x,"placed"))<=84,"furniture capacity exceeded");var indices=new HashSet<long>();foreach(var row in furniture){var code=N(row,"code");Require(Catalog["furniture"].ContainsKey(code),"unknown furniture");var index=N(row,"index");if(index<=0)index=Enumerable.Range(1,254).FirstOrDefault(i=>!indices.Contains(i));Require(index is >=1 and <=254&&indices.Add(index)&&(!B(row,"placed")||index<=84),"invalid/duplicate furniture index");Require(N(row,"x",400) is >=-32768 and <=32767&&N(row,"y",300) is >=-32768 and <=32767&&N(row,"z") is >=0 and <=255&&N(row,"mirror") is 0 or 1,"invalid furniture placement");row["index"]=index;row["type"]=N(Catalog["furniture"][code],"type");}
        Require(N(shop,"coin")>=0&&N(shop,"nana")>=0,"currency out of range");state["clothing"]=Arr(clothes.Cast<object>());state["pets"]=Arr(pets.Select(code=>(object)Obj(new{code,upgrade_material=petValues[code].Item1,gems=petValues[code].Item2})));return new(state,clothes,pets,petValues);
    }
    static JsonObject Apply(string hex,JsonObject state,long? id,JsonObject? copySource=null,int? titleGrade=null,string? titleRoot=null)
    {
        ValidateHex(hex);Require(titleGrade is null||titleGrade is >=0 and <=42,"dungeon grade out of range");
        titleRoot=Path.GetFullPath(titleRoot??Root);
        if(id is null&&copySource is null){
            var name=ValidateHex(hex);var rows=Profiles("");
            var match=rows.Where(r=>r?["account_id"] is not null&&S(r,"username").Equals(name,StringComparison.OrdinalIgnoreCase)).ToArray();
            if(match.Length==0)match=rows.Where(r=>r?["character_id"] is not null&&S(r,"character_name").Equals(name,StringComparison.OrdinalIgnoreCase)).ToArray();
            Require(match.Length<=1,"ambiguous database profile identity");
            if(match.Length==1){Require(match[0]!["character_id"] is not null,"selected account has no character yet");id=N(match[0],"character_id");}
        }
        if(id is not null)return DbApply(id.Value,hex,state,titleGrade,titleRoot);
        var path=DraftPath(hex);var existing=copySource??Snapshot(hex,null);
        var plan=ValidateInventory(state,Objects(existing,"cards"));state=plan.State;
        state["version"]=2;state["source"]="sidecar";state["character_id"]=null;state["name_hex"]=hex;state["account_suffix"]="p_"+hex;
        state["profile"]??=new JsonObject();state["profile"]!["character_name"]=ValidateHex(hex);
        state["profile"]!["coin"]=N(state["shop"],"coin");state["profile"]!["nana_point"]=N(state["shop"],"nana");
        if(titleGrade is not null)state["profile"]!["dungeon_grade"]=titleGrade.Value;
        // Preserve legacy import once, before taking the edit lock. No raw files are deleted.
        Store.Read(path);
        string? sourcePath=copySource is not null&&S(copySource,"source")=="sidecar"?DraftPath(S(copySource,"name_hex")):null;
        var saveSource=sourcePath is not null&&Store.Read(sourcePath) is null;
        var titlePath=titleGrade is not null?Path.Combine(titleRoot,"dungeon_grade_state_v1_"+hex+".dat"):null;
        if(titlePath is not null)Store.Read(titlePath);
        using var c=Store.Open();using var t=c.BeginTransaction(deferred:false);
        var stored=ReadState(c,t,path);
        if(copySource is not null)Require(stored is null,"target profile already exists; select it instead");
        if(Table(c,"Characters",t)&&Table(c,"Accounts",t))Require(Rows(c,t,"SELECT c.Id FROM Characters c JOIN Accounts a ON a.Id=c.AccountId WHERE a.Username=$name COLLATE NOCASE OR c.Name=$name COLLATE NOCASE",("$name",ValidateHex(hex))).Count==0,"Profile was registered while saving; reload the database character before retrying");
        var draftChanged=stored is null||Canonical(JsonNode.Parse(stored))!=Canonical(state);
        var titleBytes=titleGrade is not null?TitleBytes(titleGrade.Value):null;
        var titleChanged=titlePath is not null&&!Same(ReadState(c,t,titlePath),titleBytes);
        var domains=new List<string>();if(draftChanged||saveSource)domains.Add("draft");if(titleChanged)domains.Add("title");
        if(domains.Count==0){t.Commit();return Obj(new{source="database-draft",account_suffix="p_"+hex,backup=(string?)null,changed=false,domains,files=new[]{Db}});}
        var backup=BackupDb();
        if(saveSource)PersistentStateStore.Write(c,t,sourcePath!,Encoding.UTF8.GetBytes(copySource!.ToJsonString()));
        if(draftChanged)PersistentStateStore.Write(c,t,path,Encoding.UTF8.GetBytes(state.ToJsonString()));
        if(titleChanged)PersistentStateStore.Write(c,t,titlePath!,titleBytes);
        t.Commit();return Obj(new{source="database-draft",account_suffix="p_"+hex,backup,changed=true,domains,title_state_path=titlePath,files=new[]{Db}});
    }
    // Object property order and inventory enumeration order are not changes.
    static string Canonical(JsonNode? node)
    {
        if(node is JsonObject obj)return "{"+string.Join(",",obj.OrderBy(x=>x.Key,StringComparer.Ordinal).Select(x=>JsonSerializer.Serialize(x.Key)+":"+Canonical(x.Value)))+"}";
        if(node is JsonArray array)return "["+string.Join(",",array.Select(Canonical))+"]";
        return node?.ToJsonString()??"null";
    }
    static byte[]? ReadState(SqliteConnection c,SqliteTransaction t,string path)
    {
        var key=PersistentStateStore.Key(path,Db);
        var rows=Rows(c,t,"SELECT Content FROM NativeState WHERE Scope=$scope AND Name=$name",("$scope",key.Scope),("$name",key.Name));
        return rows.Count>0&&rows[0]["Content"] is byte[] bytes?bytes:null;
    }
    static byte[] TitleBytes(int grade)=>Encoding.ASCII.GetBytes($"version=1\ngrade={grade}\nfrontier_valid=0\nfrontier_hd=0\nfrontier_episode=0\nfrontier_dungeon=0\nfrontier_difficulty=0\nfrontier_stage=0\n");
    static bool SameValue(object? a,object? b)=>a is byte[] x&&b is byte[] y?x.AsSpan().SequenceEqual(y):a is null||b is null||a==DBNull.Value||b==DBNull.Value?Equals(a,b):a is string||b is string?Equals(a,b):Convert.ToInt64(a)==Convert.ToInt64(b);
    sealed record Edit(string Domain,string Sql,(string,object?)[] Args);
    static JsonObject DbApply(long id,string hex,JsonObject state,int? titleGrade,string titleRoot)
    {
        var titlePath=titleGrade is not null?Path.Combine(titleRoot,"dungeon_grade_state_v1_"+hex+".dat"):null;
        if(titlePath is not null)Store.Read(titlePath); // migrate legacy title only once, outside edit transaction
        using var c=OpenDb();var cols=Columns(c,"Characters");var itemCols=Columns(c,"CharacterItems");using var t=c.BeginTransaction(deferred:false);
        var rows=Rows(c,t,"SELECT c.*,a.IsOnline account_online FROM Characters c JOIN Accounts a ON a.Id=c.AccountId WHERE c.Id=$id",("$id",id));
        Require(rows.Count==1,"selected character profile no longer exists");var current=rows[0];
        Require(Hex((string)current["Name"]).Equals(hex,StringComparison.OrdinalIgnoreCase),"selected character identity changed; reload before saving");
        Require(V(current,"IsOnline")==0&&V(current,"account_online")==0,"selected user is online; stop clients and adapter before editing");
        // Everything used to compute edits is read under the same BEGIN IMMEDIATE lock.
        var oldCards=Rows(c,t,"SELECT * FROM CharacterCards WHERE CharacterId=$id",("$id",id));
        var plan=ValidateInventory(state,oldCards.Select(x=>Obj(new{code=V(x,"CardCode"),count=V(x,"Quantity")})));
        state=plan.State;var profile=state["profile"]??new JsonObject();var shop=state["shop"]!;
        var now=DateTime.UtcNow.ToString("O");var edits=new List<Edit>();var domains=new HashSet<string>();
        void Add(string domain,string sql,params (string,object?)[] args){edits.Add(new(domain,sql,args));domains.Add(domain);}
        var updates=new Dictionary<string,object?>();
        void Set(string col,object? value,string domain){if(!current.TryGetValue(col,out var old)||!SameValue(old,value)){updates[col]=value;domains.Add(domain);}}
        Set("Hans",N(shop,"coin"),"shop");Set("Cash",N(shop,"nana"),"shop");
        foreach(var(key,col) in ProfileFields)if(cols.Contains(col)&&profile[key] is not null){
            long value=N(profile,key);Require(value>=0&&value<=(col is "MaxHp" or "MaxMp" or "DefenseFlat"?65535:col=="AttackModifier"?1000000:uint.MaxValue),"profile value out of range: "+key);Set(col,value,"profile");
        }
        foreach(var(which,column,currentCol) in new[]{("hp","MaxHp","CurrentHp"),("mp","MaxMp","CurrentMp")})if(cols.Contains(currentCol)){
            var max=updates.TryGetValue(column,out var configured)?Convert.ToInt64(configured):V(current,column);
            if(profile[which+"_current"] is not null||updates.ContainsKey(column)){
                var value=N(profile,which+"_current",max);Require(value>=0,"negative current resource");Set(currentCol,Math.Min(value,max),"profile");
            }
        }
        if(profile["skill_slot_z"] is not null||profile["skill_slot_x"] is not null||Enumerable.Range(0,16).Any(i=>profile["skill_grade"+i] is not null)){
            Require(cols.Contains("SelectedSkill0")&&cols.Contains("SelectedSkill1"),"database skill schema is missing");
            var old=Rows(c,t,"SELECT SkillCode,Grade FROM CharacterSkills WHERE CharacterId=$id",("$id",id)).ToDictionary(x=>V(x,"SkillCode"),x=>V(x,"Grade"));
            var grades=Enumerable.Range(0,16).Select(i=>old.GetValueOrDefault(52000000+i)).ToArray();
            for(int i=0;i<16;i++){grades[i]=N(profile,"skill_grade"+i,grades[i]);Require(grades[i] is >=0 and <=5,"skill grade must be 0..5");}
            foreach(int start in new[]{0,8})Require(!new[]{2,4,6}.Any(i=>grades[start+i]>0)||!new[]{3,5,7}.Any(i=>grades[start+i]>0),"conflicting skill branches");
            long z=N(profile,"skill_slot_z",V(current,"SelectedSkill0")),x=N(profile,"skill_slot_x",V(current,"SelectedSkill1"));
            foreach(var code in new[]{z,x})Require(code==0||code is >=52000000 and <52000016&&grades[code-52000000]>0,"selected skill is not learned");Require(z==0||z!=x,"Z and X must be different skills");
            Set("SelectedSkill0",z,"skills");Set("SelectedSkill1",x,"skills");
            for(int i=0;i<16;i++)if(profile["skill_grade"+i] is not null&&old.GetValueOrDefault(52000000+i)!=grades[i]){
                if(grades[i]>0)Add("skills","INSERT INTO CharacterSkills(CharacterId,SkillCode,Grade,UpdatedAt) VALUES($id,$code,$grade,$now) ON CONFLICT(CharacterId,SkillCode) DO UPDATE SET Grade=excluded.Grade,UpdatedAt=excluded.UpdatedAt",("$id",id),("$code",52000000+i),("$grade",grades[i]),("$now",now));
                else Add("skills","DELETE FROM CharacterSkills WHERE CharacterId=$id AND SkillCode=$code",("$id",id),("$code",52000000+i));
            }
        }
        if(B(profile,"skill_slot_expiry_apply")){
            long expiry=N(profile,"skill_slot_expiry");Require(expiry==0||expiry is >=2000010100 and <=2100123123&&DateTime.TryParseExact(expiry.ToString(),"yyyyMMddHH",System.Globalization.CultureInfo.InvariantCulture,System.Globalization.DateTimeStyles.None,out _),"invalid Z/X slot expiry");Require(cols.Contains("SkillSlotExpansionExpires"),"missing skill expiry schema");Set("SkillSlotExpansionExpires",expiry,"skills");
        }
        var appearance=(current["Appearance"] as byte[]??[]).ToArray();if(appearance.Length<36)Array.Resize(ref appearance,36);
        foreach(var(offset,code) in new[]{0,4,8,12,20}.Zip(A(shop,"equipped").Select(x=>Num(x))))BinaryPrimitives.WriteUInt32LittleEndian(appearance.AsSpan(offset),checked((uint)code));
        long selected=N(shop,"selected_pet");BinaryPrimitives.WriteUInt32LittleEndian(appearance.AsSpan(24),checked((uint)N(shop,"effect")));BinaryPrimitives.WriteUInt32LittleEndian(appearance.AsSpan(28),checked((uint)selected));BinaryPrimitives.WriteUInt32LittleEndian(appearance.AsSpan(32),checked((uint)V(current,"Gender")));
        Set("Appearance",appearance,"shop");Set("EquippedPetItemCode",selected,"shop");
        if(selected!=V(current,"EquippedPetItemCode")&&cols.Contains("EquippedPetInstanceId"))Set("EquippedPetInstanceId",0,"shop");
        var oldItems=Rows(c,t,"SELECT * FROM CharacterItems WHERE CharacterId=$id",("$id",id)).ToDictionary(x=>V(x,"ItemCode"));
        var wanted=new Dictionary<long,(string Domain,Dictionary<string,object?> Values)>();
        void Item(string domain,long code,long qty,Dictionary<string,object?>? extra=null){
            var values=new Dictionary<string,object?>{{"Quantity",qty}};
            if(extra is not null)foreach(var entry in extra)if(itemCols.Contains(entry.Key))values[entry.Key]=entry.Value;
            wanted[code]=(domain,values);
        }
        foreach(var code in plan.Clothes)Item("clothing",code,1);
        foreach(var code in plan.Pets){
            var(upgrade,gems)=plan.PetValues[code];var values=new Dictionary<string,object?>{{"PetAccessory0",gems[0]},{"PetAccessory1",gems[1]},{"PetAccessory2",gems[2]}};
            if(itemCols.Contains("PetCurrentStage")){
                var stage=oldItems.TryGetValue(code,out var item)?V(item,"PetCurrentStage"):0;
                values["PetCurrentStage"]=upgrade==(stage>0?N(Catalog["pets"][code],"upgrade_material"):0)?stage:upgrade>0?1:0;
            }
            Item("pets",code,1,values);
        }
        foreach(var row in Objects(state,"game_items"))Item("game_items",N(row,"code"),N(row,"count"));
        foreach(var group in Objects(state,"furniture").GroupBy(x=>N(x,"code")))Item("furniture",group.Key,group.Count());
        string? Kind(long code)=>Catalog["clothing"].ContainsKey(code)?"clothing":Catalog["pets"].ContainsKey(code)?"pets":Catalog["game"].ContainsKey(code)?"game_items":Catalog["furniture"].ContainsKey(code)?"furniture":null;
        foreach(var(code,old) in oldItems)if(Kind(code) is {} domain&&!wanted.ContainsKey(code))Add(domain,"DELETE FROM CharacterItems WHERE CharacterId=$id AND ItemCode=$code",("$id",id),("$code",code));
        foreach(var(code,row) in wanted){
            if(oldItems.TryGetValue(code,out var old)&&row.Values.All(v=>SameValue(old.GetValueOrDefault(v.Key),v.Value)))continue;
            var values=new Dictionary<string,object?>(row.Values){{"CharacterId",id},{"ItemCode",code},{"UpdatedAt",now}};
            var names=values.Keys.ToArray();Add(row.Domain,"INSERT INTO CharacterItems("+string.Join(',',names)+") VALUES("+string.Join(',',names.Select(k=>"$"+k))+") ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET "+string.Join(',',row.Values.Keys.Append("UpdatedAt").Select(k=>k+"=excluded."+k)),values.Select(x=>("$"+x.Key,x.Value)).ToArray());
        }
        if(selected!=V(current,"EquippedPetItemCode"))foreach(var col in new[]{"PetLevel","PetExperience"})if(cols.Contains(col))Set(col,oldItems.TryGetValue(selected,out var pet)&&itemCols.Contains(col)?V(pet,col):0,"shop");
        var desiredCards=Objects(state,"cards").Where(x=>Catalog["cards"].ContainsKey(N(x,"code"))).ToDictionary(x=>N(x,"code"),x=>N(x,"count"));
        var originalCards=oldCards.ToDictionary(x=>V(x,"CardCode"));
        foreach(var row in oldCards)if(Catalog["cards"].ContainsKey(V(row,"CardCode"))&&!desiredCards.ContainsKey(V(row,"CardCode")))Add("cards","DELETE FROM CharacterCards WHERE CharacterId=$id AND CardCode=$code",("$id",id),("$code",V(row,"CardCode")));
        foreach(var(code,qty) in desiredCards)if(!originalCards.TryGetValue(code,out var old)||V(old,"Quantity")!=qty)Add("cards","INSERT INTO CharacterCards(CharacterId,CardCode,Quantity,UpdatedAt) VALUES($id,$code,$qty,$now) ON CONFLICT(CharacterId,CardCode) DO UPDATE SET Quantity=excluded.Quantity,UpdatedAt=excluded.UpdatedAt",("$id",id),("$code",code),("$qty",qty),("$now",now));
        var placements=Rows(c,t,"SELECT * FROM CharacterApartmentItems WHERE CharacterId=$id",("$id",id)).ToDictionary(x=>V(x,"SlotIndex"));
        var desiredPlacements=Objects(state,"furniture").Where(x=>B(x,"placed")).ToDictionary(x=>N(x,"index")-1);
        foreach(var slot in placements.Keys)if(!desiredPlacements.ContainsKey(slot))Add("furniture","DELETE FROM CharacterApartmentItems WHERE CharacterId=$id AND SlotIndex=$slot",("$id",id),("$slot",slot));
        foreach(var(slot,row) in desiredPlacements){
            var values=new Dictionary<string,object?>{{"ItemCode",N(row,"code")},{"PositionX",N(row,"x",400)},{"PositionY",N(row,"y",300)},{"Layer",N(row,"z")},{"Mirror",N(row,"mirror")},{"InteriorType",N(row,"type")}};
            if(placements.TryGetValue(slot,out var old)&&values.All(v=>SameValue(old.GetValueOrDefault(v.Key),v.Value)))continue;
            if(old is not null)Add("furniture","DELETE FROM CharacterApartmentItems WHERE CharacterId=$id AND SlotIndex=$slot",("$id",id),("$slot",slot));
            values["CharacterId"]=id;values["SlotIndex"]=slot;values["UpdatedAt"]=now;var names=values.Keys.ToArray();Add("furniture","INSERT INTO CharacterApartmentItems("+string.Join(',',names)+") VALUES("+string.Join(',',names.Select(k=>"$"+k))+")",values.Select(x=>("$"+x.Key,x.Value)).ToArray());
        }
        bool nativeTitleChanged=false,sideTitleChanged=false;
        if(titleGrade is not null){
            Require(V(current,"CurveVersion")==CharacterProgression.CurveVersion,"Offline level200 migration required");
            CharacterProgression.Validate(checked((int)V(current,"Level")),V(current,"Experience"));
            var native=Table(c,"NativeDungeonProfiles",t)?Rows(c,t,"SELECT State FROM NativeDungeonProfiles WHERE CharacterId=$id",("$id",id)):[];
            if(native.Count>0&&native[0]["State"] is byte[] saved&&NativeDungeonState.IsSupportedSize(saved.Length))_ = new NativeDungeonState(saved);
            var expected=new byte[NativeDungeonState.DungeonGradeStateLength];BinaryPrimitives.WriteUInt32LittleEndian(expected,checked((uint)titleGrade.Value));
            nativeTitleChanged=native.Count==0||native[0]["State"] is not byte[] data||!NativeDungeonState.IsSupportedSize(data.Length)||!data.AsSpan(NativeDungeonState.DungeonGradeOffset,expected.Length).SequenceEqual(expected);
            sideTitleChanged=!Same(ReadState(c,t,titlePath!),TitleBytes(titleGrade.Value));
            if(nativeTitleChanged||sideTitleChanged)domains.Add("title");
        }
        if(domains.Count==0){t.Commit();return Obj(new{source="database",character_id=id,account_suffix="p_"+hex,backup=(string?)null,changed=false,domains=Array.Empty<string>(),files=new[]{Db}});}
        // The same read-lock protects the plan; backup uses a separate reader and
        // completes before any pending edit or title upgrade modifies the DB.
        var backup=BackupDb();
        if(updates.Count>0){if(cols.Contains("LastSavedAt"))updates["LastSavedAt"]=now;Update(c,t,"Characters",updates,"Id",id);}
        foreach(var edit in edits)Exec(c,t,edit.Sql,edit.Args);
        if(nativeTitleChanged)ApplyTitle(c,t,id,titleGrade!.Value,current);
        if(sideTitleChanged)PersistentStateStore.Write(c,t,titlePath!,TitleBytes(titleGrade!.Value));
        t.Commit();return Obj(new{source="database",character_id=id,account_suffix="p_"+hex,backup,changed=true,domains=domains.OrderBy(x=>x).ToArray(),edit_count=edits.Count,title_state_path=titlePath,files=new[]{Db}});
    }
    static void ApplyTitle(SqliteConnection c,SqliteTransaction t,long id,int grade,Dictionary<string,object> current)
    {
        Exec(c,t,"CREATE TABLE IF NOT EXISTS NativeDungeonProfiles(CharacterId INTEGER PRIMARY KEY REFERENCES Characters(Id),State BLOB NOT NULL)");
        var saved=Rows(c,t,"SELECT State FROM NativeDungeonProfiles WHERE CharacterId=$id",("$id",id));
        var data=saved.Count>0&&saved[0]["State"] is byte[] original?DatabaseService.UpgradeNativeCardProfileAsync(c,t,id,original).GetAwaiter().GetResult():new byte[NativeDungeonState.Size];
        BinaryPrimitives.WriteUInt32LittleEndian(data,NativeDungeonState.ProtocolVersion);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(NativeDungeonState.VersionOffset),NativeDungeonState.ProtocolVersion);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(NativeDungeonState.LengthOffset),NativeDungeonState.Size);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(NativeDungeonState.CurveVersionOffset),CharacterProgression.CurveVersion);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(8),checked((uint)V(current,"Level")));BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(12),0);
        BinaryPrimitives.WriteUInt64LittleEndian(data.AsSpan(NativeDungeonState.TotalExperienceOffset),checked((ulong)V(current,"Experience")));
        data.AsSpan(NativeDungeonState.DungeonGradeOffset,NativeDungeonState.DungeonGradeStateLength).Clear();BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(NativeDungeonState.DungeonGradeOffset),checked((uint)grade));
        Exec(c,t,"INSERT INTO NativeDungeonProfiles(CharacterId,State) VALUES($id,$state) ON CONFLICT(CharacterId) DO UPDATE SET State=excluded.State",("$id",id),("$state",data));
    }
    static string BackupDb()
    {
        Require(File.Exists(Db),"database is missing");var directory=Path.Combine(Root,"inventory_admin_backups",DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);var path=Path.Combine(directory,"game.db");using var source=OpenDb();using var destination=new SqliteConnection(new SqliteConnectionStringBuilder{DataSource=path,Pooling=false}.ToString());destination.Open();source.BackupDatabase(destination);return path;
    }
    static void Update(SqliteConnection c,SqliteTransaction t,string table,Dictionary<string,object?> values,string idColumn,long id)=>Exec(c,t,"UPDATE "+table+" SET "+string.Join(',',values.Keys.Select(k=>k+"=$"+k))+" WHERE "+idColumn+"=$id",values.Select(x=>("$"+x.Key,x.Value)).Append(("$id",(object?)id)).ToArray());
}

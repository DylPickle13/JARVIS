#include "razer_bridge.hpp"
#include <cassert>
#include <future>
using namespace jarvis::razer;
json body(std::string action = "apply") {
  return {{"operation_type", "jarvis_razer_v1"}, {"action", action},
          {"id", "0123456789abcdef0123456789abcdef"}, {"sent_at", wall_time()},
          {"settings", action == "apply" ? json{{"operation","effect"},{"value",1},{"y",0}} : json(nullptr)}};
}
json invoke(json request, bridge::transport send, const std::filesystem::path& path) {
  auto promise = std::make_shared<std::promise<json>>(); auto future = promise->get_future();
  bridge::handle(request, send, [promise](json r) { promise->set_value(r); }, path);
  assert(future.wait_for(std::chrono::seconds(4)) == std::future_status::ready);
  auto r = future.get(); std::this_thread::sleep_for(std::chrono::milliseconds(10)); return r;
}
int main() {
  auto steady = *encode({"effect",1,0});
  assert(steady[5] == 9 && steady[6] == 15 && steady[7] == 2 && steady[10] == 1);
  assert(steady[88] == crc(steady));
  for (int b = 0; b <= 100; ++b) assert((*encode({"brightness",b,0}))[10] == (b*255+50)/100);
  for (auto invalid : {settings{"effect",3,0}, settings{"effect",1,1}, settings{"brightness",101,0},
                       settings{"dpi",99,100}, settings{"dpi",6401,100}, settings{"poll",250,0},
                       settings{"get-dpi",1,0}, settings{"raw",0,0}}) assert(!encode(invalid));
  auto dpi = *encode({"dpi",800,1600});
  assert(dpi[1] == 255 && dpi[6] == 4 && dpi[7] == 5 && dpi[9] == 3 && dpi[10] == 32 && dpi[11] == 6 && dpi[12] == 64);
  for (int hz : {125,500,1000}) assert((*encode({"poll",hz,0}))[8] == 1000/hz);
  auto response = steady; response[0] = 2; assert(decode(steady,response,90));
  for (int pos : {0,1,2,3,4,5,6,7,88,89}) {
    auto bad = response; bad[pos] ^= 1; assert(!decode(steady,bad,90));
  }
  assert(!decode(steady,response,89));
  auto query = *encode({"get-dpi",0,0}); response = query; response[0] = 2;
  response[9] = 3; response[10] = 32; response[11] = 6; response[12] = 64; response[88] = crc(response);
  assert(decode(query,response,90)->at("dpi_x") == 800);
  assert(!matches(nullptr));

  // A retained CF object stands in for a device; injected I/O never touches HID.
  auto fake = reinterpret_cast<IOHIDDeviceRef>(const_cast<void*>(static_cast<const void*>(CFSTR("fake"))));
  IOHIDReportCallback wrote = nullptr, got = nullptr; void* write_context = nullptr; void* read_context = nullptr;
  report* reply = nullptr; std::function<void()> delayed;
  int writes = 0, reads = 0, completions = 0;
  auto writer = [&](auto, const auto& r, auto cb, auto ctx) { ++writes; assert(r == steady); wrote=cb;write_context=ctx;return kIOReturnSuccess; };
  auto reader = [&](auto, auto& r, auto length, auto cb, auto ctx) { ++reads;assert(*length==90);reply=&r;got=cb;read_context=ctx;return kIOReturnSuccess; };
  auto delay = [&](auto task) { delayed=task; };
  auto deadline = [] { return async_sender::clock::now()+std::chrono::seconds(2); };
  {
    async_sender sender(writer,reader,delay);
    assert(sender.submit(fake,{"effect",1,0},true,deadline(),[&](auto r){assert(r.status==outcome::transport_success);++completions;}));
    assert(!sender.acknowledge());
    assert(!sender.submit(fake,{"effect",1,0},true,deadline(),[](auto){}));
    wrote(write_context,kIOReturnSuccess,nullptr,kIOHIDReportTypeFeature,0,steady.data(),90);
    assert(reads==0); delayed(); assert(reads==1);
    *reply=steady;(*reply)[0]=2;
    got(read_context,kIOReturnSuccess,nullptr,kIOHIDReportTypeFeature,0,reply->data(),90);
    assert(completions==1 && sender.status()==async_sender::state::ready);
  }
  {
    auto sender = std::make_unique<async_sender>(writer,reader,delay);
    assert(sender->submit(fake,{"effect",1,0},true,deadline(),[&](auto r){assert(r.status==outcome::uncertain);++completions;}));
    wrote(write_context,kIOReturnSuccess,nullptr,kIOHIDReportTypeFeature,0,steady.data(),90);
    sender->mark_uncertain(); assert(!sender->acknowledge()); sender.reset();
    delayed(); assert(reads==1 && completions==2); // no get after stop, lifetime safe
  }
  {
    async_sender sender(writer,reader,delay);
    assert(sender.submit(fake,{"effect",1,0},true,deadline(),[&](auto r){assert(r.status==outcome::uncertain);++completions;}));
    wrote(write_context,kIOReturnSuccess,nullptr,kIOHIDReportTypeFeature,0,steady.data(),90); delayed();
    *reply=steady; (*reply)[0]=1; // busy is NOT confirmed success
    got(read_context,kIOReturnSuccess,nullptr,kIOHIDReportTypeFeature,0,reply->data(),90);
    assert(sender.status()==async_sender::state::blocked); assert(sender.acknowledge());
  }
  assert(writes==3 && reads==2 && completions==3);

  char pattern[]="/tmp/jarvis-razer-test-XXXXXX"; auto parent=mkdtemp(pattern); assert(parent);
  auto dir=std::filesystem::path(parent)/"state"; jarvis::ak820::journal store(dir);
  for (auto v : {json(true),json(1.5),json(-1),json(1ULL<<63),json(3)}) {
    auto b=body();b["settings"]["value"]=v; assert(invoke(b,{},dir).at("status")=="rejected");
  }
  auto invalid=body();invalid["sent_at"]=wall_time()-3;assert(invoke(invalid,{},dir).at("status")=="rejected");
  invalid=body();invalid["settings"]["raw"]=1;assert(invoke(invalid,{},dir).at("status")=="rejected");
  int sends=0;
  bridge::transport success=[&](const request& r,auto,auto done){
    if(r.action=="apply"){assert(store.load().at("pending").get<bool>());++sends;}
    done({outcome::transport_success,kIOReturnSuccess,json{{"example",1}}});
  };
  assert(invoke(body(),success,dir).at("data").at("example")==1);
  assert(invoke(body(),success,dir).at("status")=="rejected");
  auto reset=[&]{auto s=store.load();s["last_attempt"]=0;s["id"]="";store.save(s);};reset();
  async_sender::completion late;
  bridge::transport timeout=[&](const request&,auto,auto done){++sends;late=done;};
  assert(invoke(body(),timeout,dir).at("status")=="uncertain");
  late({outcome::transport_success,kIOReturnSuccess});
  assert(store.load().at("pending").get<bool>());
  assert(invoke(body(),success,dir).at("status")=="blocked");
  assert(invoke(body("acknowledge"),success,dir).at("status")=="acknowledged");
  assert(sends==2 && !store.load().at("pending").get<bool>());
  std::filesystem::remove_all(parent);
}

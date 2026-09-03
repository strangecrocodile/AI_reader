let selectedText=''; 
const $=id=>document.getElementById(id);
function openModal(){
    $('modal').classList.add('open')
} 
function closeModal(){
    $('modal').classList.remove('open')
} 
function chooseBook(name,p){
    $('book-cover').innerHTML=name.replace(' ','<br>');$('book-tag').textContent=name.split(' ')[0];$('book-progress').textContent=p;closeModal();toast('已切换为《'+name+'》')
}
function openStudy(){$('home').classList.remove('active');$('study').classList.add('active');window.scrollTo(0,0)} function openHome(){$('study').classList.remove('active');$('home').classList.add('active')}
function focusSource(id){const el=$(id);el.scrollIntoView({behavior:'smooth',block:'center'});document.querySelectorAll('.source').forEach(x=>x.classList.remove('focus'));el.classList.add('focus');setTimeout(()=>el.classList.remove('focus'),2200);toast('已定位到教材原文')}
function switchTab(name,btn){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.tab-content').forEach(x=>x.style.display='none');$(name).style.display='block'}
document.addEventListener('mouseup',()=>{const s=window.getSelection().toString().trim();if(s.length>1 && $('study').classList.contains('active')){selectedText=s.length>34?s.slice(0,34)+'…':s;$('selectionLabel').classList.add('show');$('selectionLabel').querySelector('span').textContent='「'+selectedText+'」';$('question').focus();$('question').placeholder='围绕这段原文提问…'}})
function ask(){const input=$('question'),q=input.value.trim();if(!q)return;const chat=$('chat');chat.classList.add('show');const context=selectedText?'（针对你选中的原文）':'';chat.innerHTML='<div class="bubble">'+escapeHtml(q)+context+'</div><div class="bubble answer"><b>AI讲师</b><br>'+answerFor(q)+'</div>';input.value='';selectedText='';$('selectionLabel').classList.remove('show');$('question').placeholder='就当前章节提问，例如：为什么一定要取极限？';chat.parentElement.scrollTop=chat.offsetTop;}
function answerFor(q){if(q.includes('极限')||q.includes('为什么'))return '因为我们要描述的是「某一瞬间」的变化，而平均变化率一定跨着一段区间。让 Δx 不断变小，才能把这段区间压缩到目标时刻；极限存在，说明逼近的结果是稳定、唯一的。';return '这段话先定义了自变量的增量 Δx，再由它得到函数增量 Δy。接下来用 Δy / Δx 表示平均变化率；当 Δx 趋近于 0 时，它的极限就是导数。你可以继续追问其中任一个符号。'}
function escapeHtml(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))} function toast(msg){const n=$('notice');n.textContent=msg;n.classList.add('show');setTimeout(()=>n.classList.remove('show'),2300)}